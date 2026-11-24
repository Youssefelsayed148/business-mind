"""Which Many routes an SSO *client* session may reach (identity design 2.5, R9).

Deny by default. Only workspace-scoped routes are listed: each one resolves a
membership from X-Workspace-Id, so a client token can only act inside the
workspace it was exchanged for. Everything else is denied to client tokens,
including every Instagram route (their handlers never filter by workspace),
campaigns, conversations, messages, leads, logs, stats and meta routes
(decisions D1 and D2).

Matching uses the route template that FastAPI selected AND the request path,
and both must agree; a mismatch denies.
"""

CLIENT_SCOPED_ROUTE_PREFIXES = (
    "/whatsapp",
    "/facebook",
    "/workspaces",
    "/privacy/contact-erasure",
)
CLIENT_SCOPED_EXACT_ROUTES = ("/auth/me",)


def _matches(path: str | None) -> bool:
    if not path:
        return False
    if path in CLIENT_SCOPED_EXACT_ROUTES:
        return True
    return any(path == p or path.startswith(p + "/") for p in CLIENT_SCOPED_ROUTE_PREFIXES)


def client_scope_allows(route_template: str | None, request_path: str | None) -> bool:
    return _matches(route_template) and _matches(request_path)
