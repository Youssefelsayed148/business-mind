#!/usr/bin/env bash
# Verifies the internal PKI: chains to the CA, names match, not expiring soon.
#   scripts/tls/check_internal_pki.sh <pki-dir> [min-days, default 30]
# Exit 0 = all fine, 1 = a problem (printed). Safe to run from cron (see docs/staging/6A).
set -uo pipefail
dir="${1:-}"; days="${2:-30}"
[ -d "$dir" ] || { echo "usage: $0 <pki-dir> [min-days]" >&2; exit 2; }
bad=0
for name in many-api saas-api; do
  openssl verify -CAfile "$dir/ca.pem" -verify_hostname "$name" "$dir/$name.pem" >/dev/null 2>&1 \
    || { echo "FAIL $name: does not verify against ca.pem for host $name"; bad=1; }
  openssl x509 -in "$dir/$name.pem" -noout -checkend $((days*86400)) >/dev/null \
    || { echo "FAIL $name: expires within $days days"; bad=1; }
done
openssl x509 -in "$dir/ca.pem" -noout -checkend $((days*86400)) >/dev/null \
  || { echo "FAIL ca: expires within $days days"; bad=1; }
[ $bad -eq 0 ] && echo "OK internal PKI (chain, names, >= $days days left)"
exit $bad
