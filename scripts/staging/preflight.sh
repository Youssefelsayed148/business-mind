#!/usr/bin/env bash
# Checks before a staging deploy. Changes nothing. Prints names, never values.
#   scripts/staging/preflight.sh
source "$(dirname "$0")/common.sh"
bad=0
fail() { echo "FAIL $*"; bad=1; }
ok() { echo "OK   $*"; }

[ -f "$ENV_FILE" ] && ok "$ENV_FILE exists" || { fail "$ENV_FILE missing (copy .env.staging.example)"; exit 1; }
mode=$(stat -c %a "$ENV_FILE"); [ "$mode" = "600" ] && ok "$ENV_FILE mode 600" || fail "$ENV_FILE mode is $mode, run chmod 600"
left=$(env_names_with_placeholder); [ -z "$left" ] && ok "no CHANGE_ME placeholder left" || fail "placeholders left in: $(echo $left | tr '\n' ' ')"
git diff --quiet && git diff --cached --quiet && ok "working tree clean at $(git rev-parse --short HEAD)" || fail "uncommitted changes in the checkout"
"${COMPOSE[@]}" config -q 2>/dev/null && ok "compose config valid" || fail "compose config failed (run it by hand to read the error)"
for f in ca.pem ca-bundle.pem many-api.pem many-api.key saas-api.pem saas-api.key; do
  [ -r "$(grep -E '^PKI_DIR=' "$ENV_FILE" | cut -d= -f2-)/$f" ] || fail "PKI file missing: $f"
done
scripts/tls/check_internal_pki.sh "$(grep -E '^PKI_DIR=' "$ENV_FILE" | cut -d= -f2-)" 30 || bad=1
le="$(grep -E '^LETSENCRYPT_DIR=' "$ENV_FILE" | cut -d= -f2-)"
[ -r "$le/live/edge/fullchain.pem" ] && ok "edge certificate present" || fail "no $le/live/edge/fullchain.pem (certbot step in docs/staging/6A)"
for flag in IDENTITY_V2_ENABLED SSO_ISSUER_ENABLED MANY_PROXY_ENABLED SSO_ASSERTION_ENABLED DATA_UNIFICATION_ENABLED; do
  v=$(grep -E "^$flag=" "$ENV_FILE" | cut -d= -f2-)
  [ "${v:-false}" = "false" ] && ok "$flag is false" || echo "NOTE $flag is $v (allowed only after 6G; say so in the report)"
done
[ $bad -eq 0 ] && echo "PREFLIGHT PASSED" || { echo "PREFLIGHT FAILED"; exit 1; }
