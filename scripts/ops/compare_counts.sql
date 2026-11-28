-- Row counts for every table outside pg_catalog / information_schema.
-- Used by scripts/ops/backup_all.sh (source side) and scripts/ops/restore_drill.sh (restored side)
-- so both sides run the exact same query. Read-only.
-- Run: psql -X -At -F "$(printf '\t')" -v ON_ERROR_STOP=1 < compare_counts.sql
-- Output: one line per table, "schema.table<TAB>exact_row_count", sorted by name.
SELECT format('SELECT %L AS t, count(*) FROM %I.%I',
              n.nspname || '.' || c.relname, n.nspname, c.relname)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg\_toast%'
ORDER BY n.nspname, c.relname
\gexec
