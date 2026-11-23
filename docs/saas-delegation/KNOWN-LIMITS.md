# SaaS delegation: known limits and operational notes

## Response compression (contract A14)
Many must not compress the `202` body of `POST /api/saas/messages` (the SaaS sends `Accept-Encoding: identity`).
- `nginx/default.conf`: `gzip off` for `location /api/saas/` and `location /saas/` (the global `gzip on` stays for everything else). The FastAPI app itself adds no compression middleware.
- `docker-compose.traefik.yml` (the production routing in this repo) defines no `compress` middleware for the API router, so nothing compresses there. If the platform in front of Traefik (Dokploy) adds one, exclude `PathPrefix(/api/saas)`.

## Signed endpoint rate limit (T3)

`nginx/default.conf` defines a separate `saas_signed:10m` zone keyed by `$binary_remote_addr`: **100 requests/second per source IP, burst 200, nodelay**. Both `/api/saas/` and `/saas/` share this budget (messages and health requests together), so switching aliases does not double the allowance. Rejections return **429** via location-scoped `limit_req_status`; both locations retain `gzip off` and their original `proxy_pass` lines. The Meta webhook zone and all other locations are unchanged.

The SaaS sends only a few messages/second per connection. At an illustrative 3 requests/second, 100 requests/second leaves room for roughly 30 concurrently active connections behind one IP plus health traffic; the 200 excess-request burst absorbs short synchronized sends/retries without nginx delaying accepted requests. These are conservative initial values, not a measured capacity guarantee. Connections sharing an egress IP share the budget, so larger aggregates can still receive 429; tune against observed peak aggregate traffic before scaling. The key is the peer IP nginx sees, not an untrusted connection-id/header. If a reverse proxy fronts nginx, all its callers may share that proxy's budget unless trusted real-IP handling is configured separately.

This protection applies only to traffic through this nginx config. The production Traefik routing does not acquire these limits from this change. No production configuration was changed or deployed. nginx syntax (`nginx -t`) and runtime rate/rejection behavior are **UNVERIFIED**: no nginx executable was found on the session PATH; no Docker was used.

## `webhook_unhealthy` is provider-wide
`services/saas_health.py` derives `webhook_unhealthy` from the shared `webhook_health` record, which is kept per provider (`meta`), not per channel. One failing Meta webhook therefore marks EVERY delegated channel (WhatsApp, Messenger and Instagram alike) as `webhook_unhealthy` and the SaaS shows them all degraded, even channels whose own webhooks are fine. This is deliberate for now (there is no per-channel webhook health to read) and needs no action; when several channels go degraded at once, check Many's webhook processing first.

## Base-URL DNS check has a time-of-check gap
In production `validate_base_url()` rejects non-https URLs and hosts that are, or resolve to, private/loopback/link-local/reserved addresses. It runs when the setting is saved and again before every forward attempt, but the HTTP client then resolves the hostname itself. A DNS answer that changes between the check and the connection (DNS rebinding) could point the request at a private address. Impact is limited: the request carries only a signed event body, redirects are not followed, no response body is used, and the URL can only be set by an owner/admin. Pinning the resolved address would mean connecting to the IP with the original `Host`/SNI, which changes the request URL that tests and logs rely on; it was judged not a small change and was not done. Mitigation if needed: restrict Many's egress to the SaaS address at the network level.

## Failed events
See the README SaaS delegation section: failed forwards keep their payload 7 days (admin "Retry failed events"), terminal rows and outbound idempotency records are deleted after 30 days.
