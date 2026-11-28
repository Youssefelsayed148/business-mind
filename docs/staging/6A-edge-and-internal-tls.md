# Phase 6A: edge TLS and internal TLS

Status: **written 2026-11-28; static checks only.** What ran: `scripts/test_edge_tls.py` (8 tests: the private CA really verifies, a wrong service name and a missing CA are refused, the CA key is not in the mounted folder, `nginx -t` accepts `nginx/unified.conf` in the dev mode and in the HTTPS plus verified-upstream mode), `scripts/test_unified_nginx.py` (4 static tests, unchanged), and `docker compose config` for the base file, the e2e overlay and the prod overlay. **Not run:** any container (no Docker engine here), `scripts/dev-up.sh test`, a real certificate request, a real TLS handshake between the services. The first real run is the staging stack (6B). Decisions D1 and D2 were approved as recommended.

## What changed

| Piece | Change |
|---|---|
| `nginx/unified.conf` | Same deny rules. The `listen` lines and the upstream TLS directives now come from two mounted folders; the two API upstreams use `${UPSTREAM_SCHEME}`; `proxy_ssl_name` is `many-api` on the Many host and `saas-api` on the SaaS hosts |
| `nginx/edge/http`, `nginx/upstream/plain` | The dev set (port 80, plain upstreams). `docker-compose.unified.yml` mounts them, so dev and the e2e run behave as before |
| `nginx/edge/https`, `nginx/redirect.conf.template` | Port 443 with one certificate named `edge` (TLS 1.2 and 1.3, HSTS 1 year, no session tickets); port 80 serves the certificate challenge and `/health`, redirects the three known hosts to HTTPS, and serves nothing else |
| `nginx/upstream/tls` | nginx verifies `many-api` and `saas-api` against `/pki/ca.pem` |
| `scripts/tls/make_internal_pki.sh` | Private CA (5 years) plus one certificate per service (ECDSA P-256, 397 days, SAN = service name, `localhost`, `127.0.0.1`); builds `ca-bundle.pem` = system roots + the CA; the CA key goes in `ca-private/` (mode 700, never mounted, move it offline); refuses to overwrite an existing CA |
| `scripts/tls/check_internal_pki.sh` | Verifies the chain, the names and at least 30 days left; exit 1 on a problem (use it from the alert check, 6D) |
| `docker-compose.unified.prod.yml` | Publishes 80 and 443; `many-api` and `saas-api` run uvicorn with `--ssl-keyfile/--ssl-certfile` on port 8000 and an HTTPS health check; every Python service has `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` and `CURL_CA_BUNDLE` set to `ca-bundle.pem` (public roots stay trusted, so Meta and OpenAI calls still verify); `saas-web` proxies to `https://saas-api:8000` and trusts the CA through `NODE_EXTRA_CA_CERTS`; `MANY_API_BASE_URL` defaults to `https://many-api:8000` |

## Steps on the staging or production host (owner; each needs approval)

1. Internal CA and certificates (host only, never in git):
   `scripts/tls/make_internal_pki.sh /opt/business-mind/pki`, then `scripts/tls/check_internal_pki.sh /opt/business-mind/pki`. Move `ca-private/` to offline storage after the first run. Renew the service certificates before 397 days by deleting the old `many-api.*` and `saas-api.*` files and re-running a copy of the `issue` step with the same CA (a renewal helper is a 6B item if you want one).
2. Edge certificate (UNVERIFIED here): with ports 80 free, `certbot certonly --standalone --cert-name edge -d $MANY_HOST -d $SAAS_WEB_HOST -d $SAAS_API_HOST`. Then switch renewals to the webroot method so nginx can stay up: `certbot reconfigure --cert-name edge --authenticator webroot --webroot-path /var/www/certbot`, and add a renewal hook that reloads nginx: `docker compose -f docker-compose.unified.yml -f docker-compose.unified.prod.yml exec nginx nginx -s reload`. Check with `certbot renew --dry-run`.
3. Env file (host only) adds: `PKI_DIR=/opt/business-mind/pki`, `LETSENCRYPT_DIR=/etc/letsencrypt`, `CERTBOT_WEBROOT=/var/www/certbot`, the three real hosts, `MANY_PUBLIC_URL=https://<MANY_HOST>`.
4. `docker compose -f docker-compose.unified.yml -f docker-compose.unified.prod.yml --env-file <env> config` must print without error; then start (6B).
5. The internal URLs that the apps store in channel rows (Many to SaaS, set when a channel is delegated) must be `https://saas-api:8000`; SaaS to Many is `https://many-api:8000` (env). The allowlist keeps `CHANNEL_INTERNAL_ALLOWED_HOSTS` as `saas-api` and `many-api` and still requires HTTPS in production; no policy code changed.
6. Checks from outside (6B script): `http://<host>/` answers 301 to https; `https://<host>/` answers with a valid chain; every edge deny from `e2e/phase2/check_nginx.py` still answers 403 over HTTPS; `curl --http1.1 -k` is not used.

## Rollback

Stop the stack, mount `nginx/edge/http` and `nginx/upstream/plain` again by using the base file only, and set `MANY_API_BASE_URL` back to `http://many-api:8000`. No database change is involved. Certificates are files; nothing else depends on them.

## Transport pinning for Many's double DNS resolution (design decision for you; no code written)

The earlier review noted that Many resolves the internal host name twice (validator, then HTTP client). The risk was a name that answers an allowed private address first and another address second. With internal TLS and `CHANNEL_INTERNAL_ALLOWED_HOSTS` fixed to two single-label names, a changed second answer must still present a certificate for `many-api` or `saas-api` signed by the private CA, which only the two real services hold. So the second resolution can no longer redirect traffic to a different server without failing the handshake. **Recommendation: accept this as the closing mitigation and do not change Many's resolver code** (it sits next to frozen areas and needs your approval anyway). Residual risk: someone who already controls the private CA key or one service key. Say "accept" or "pin" (then I write a separate design).

## Open items

- Real first run of everything above (6B).
- Renewal helper for the service certificates (optional, 6B).
- Many dashboard and SaaS web talk to the browser over the edge only; no other internal hop uses HTTP in the prod overlay, to be confirmed by the staging run.
- Reserved: if a CDN or load balancer is ever put in front of nginx, configure `real_ip` (Phase 3 review item 11).
