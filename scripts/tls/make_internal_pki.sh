#!/usr/bin/env bash
# Private CA and two service certificates for the internal network (Phase 6A, decision D2).
#   scripts/tls/make_internal_pki.sh <output-dir>
# Writes ca.pem, many-api.pem/.key, saas-api.pem/.key and ca-bundle.pem (system roots + this CA,
# so outbound calls to Meta and OpenAI still verify when SSL_CERT_FILE points at it).
# Keep <output-dir> on the server only, never in git. Refuses to overwrite an existing CA.
# Needs only openssl. Certificates: ECDSA P-256, 397 days; the CA 5 years.
set -euo pipefail
out="${1:-}"
[ -n "$out" ] || { echo "usage: $0 <output-dir>" >&2; exit 2; }
[ ! -e "$out/ca.pem" ] || { echo "refusing to overwrite $out/ca.pem" >&2; exit 3; }
mkdir -p "$out" "$out/ca-private"
umask 077
cd "$out"

openssl ecparam -name prime256v1 -genkey -noout -out ca-private/ca.key
openssl req -x509 -new -key ca-private/ca.key -sha256 -days 1825 -subj "/CN=business-mind internal CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" -out ca.pem

issue() { # name
  local name="$1"
  openssl ecparam -name prime256v1 -genkey -noout -out "$name.key"
  openssl req -new -key "$name.key" -subj "/CN=$name" -out "$name.csr"
  printf 'subjectAltName=DNS:%s,DNS:localhost,IP:127.0.0.1\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=serverAuth\n' "$name" > "$name.ext"
  openssl x509 -req -in "$name.csr" -CA ca.pem -CAkey ca-private/ca.key -CAcreateserial -sha256 -days 397 \
    -extfile "$name.ext" -out "$name.pem" 2>/dev/null
  rm -f "$name.csr" "$name.ext"
}
issue many-api
issue saas-api
rm -f ca.srl ca-private/*.srl

system_roots=/etc/ssl/certs/ca-certificates.crt
[ -r "$system_roots" ] || { echo "no system CA bundle at $system_roots" >&2; exit 4; }
cat "$system_roots" ca.pem > ca-bundle.pem

# Containers run as non-root users and read the service keys through a bind mount, so those files
# are world-readable on the host: protect the host directory itself (owner-only parent), as for any
# mounted secret. The CA key lives in ca-private/ (mode 700), is never mounted and should be moved offline.
chmod 644 ca.pem ca-bundle.pem many-api.pem saas-api.pem many-api.key saas-api.key
chmod 700 ca-private; chmod 600 ca-private/ca.key
echo "wrote $out: ca.pem ca-bundle.pem many-api.{pem,key} saas-api.{pem,key}; CA key in $out/ca-private (move it offline)"
