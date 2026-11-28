#!/usr/bin/env bash
# Offline checks for the 6C scripts. No Docker, no database. A fake `docker` stub stands in for the CLI,
# so this tests the shell logic only (argument refusal, file layout, checksums, count comparison),
# NOT real pg_dump / pg_restore behaviour.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; else echo "FAIL $1 (expected $3, got $2)"; fail=1; fi; }
T="$(printf '\t')"

# 1. compare-only: equal files
printf 'public.a%s3\npublic.b%s5\n' "$T" "$T" > "$W/s.tsv"; cp "$W/s.tsv" "$W/r_ok.tsv"
set +e
bash "$HERE/restore_drill.sh" --compare-only "$W/s.tsv" "$W/r_ok.tsv" > "$W/o1.txt"; check "compare equal exits 0" "$?" 0
# 2. differing count and a missing table
printf 'public.a%s3\npublic.b%s4\npublic.c%s1\n' "$T" "$T" "$T" > "$W/r_bad.tsv"
bash "$HERE/restore_drill.sh" --compare-only "$W/s.tsv" "$W/r_bad.tsv" > "$W/o2.txt"; check "compare mismatch exits 1" "$?" 1
check "mismatch lists 2 problem rows" "$(grep -c MISMATCH "$W/o2.txt")" 2
# 3. backup_all refuses without --target
bash "$HERE/backup_all.sh" > /dev/null 2>&1; check "backup_all without target exits 2" "$?" 2
# 4. restore_drill refuses a project name that does not start with drill
bash "$HERE/restore_drill.sh" --backup "$W" --project live > /dev/null 2>&1; check "restore_drill rejects non-drill project" "$?" 2
set -e

# 5. backup_all end to end with a stub docker
mkdir "$W/bin"
cat > "$W/bin/docker" <<'STUB'
#!/usr/bin/env bash
args="$*"
case "$args" in
  *pg_dump*) printf 'PGDMP-fake-archive' ;;
  *pg_restore*) cat > /dev/null; echo "; fake toc" ;;
  *alembic_version*) echo "0099_fake_head" ;;
  *psql*) cat > /dev/null; printf 'public.x\t7\n' ;;
esac
STUB
chmod +x "$W/bin/docker"
PATH="$W/bin:$PATH" bash "$HERE/backup_all.sh" --target "$W/out" > "$W/o3.txt"; check "stub backup exits 0" "$?" 0
d="$(ls -d "$W"/out/backup_*)"
for f in SHA256SUMS MANIFEST.txt counts_many.tsv counts_saas.tsv alembic_many.txt alembic_saas.txt; do
  [ -f "$d/$f" ] && check "backup has $f" ok ok || check "backup has $f" missing ok
done
check "backup has 2 dumps" "$(ls "$d"/*.dump | wc -l | tr -d ' ')" 2
( cd "$d" && sha256sum -c SHA256SUMS > /dev/null ); check "checksums verify" "$?" 0
if [ "$fail" -eq 0 ]; then echo "ALL OK"; else echo "FAILURES"; exit 1; fi
