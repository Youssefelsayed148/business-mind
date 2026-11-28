"""The paths the SaaS proxy may call on the Many API (Phase 4A, decision P1).

Deny by default: a call is forwarded only if its method and path match one entry here.
Nothing in this file imports the application, so a script can load it by path and check
every entry against Many's real route table (``scripts/test_many_proxy_allowlist.py``).

Two audiences:
- ``org``: workspace-scoped Many routes, reached as /api/v1/many/orgs/{tenant_id}/... The
  proxy sets X-Workspace-Id from the organization's mapped workspace. ``permission`` is the
  SaaS organization permission the caller needs (the same names as ``roles.py``); Many checks
  the mapped role again. ``staff_only`` entries are closed to client logins even if their
  role would allow them (Many's client-scope guard denies them as well).
- ``global``: Many routes that do not filter by workspace (Instagram, campaigns, leads,
  messages, logs, stats, conversations). Reached as /api/v1/many/staff/...; platform staff only.

Never listed, on purpose: /api/saas, /saas, /webhooks, /auth (login, SSO exchange), /meta/callback,
/meta/compliance, /health, /privacy/contact-erasure and /public.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

ORG: Final = "org"
GLOBAL: Final = "global"

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PARAM = re.compile(r"^\{[a-z_]+\}$")
_UNSAFE = re.compile(r"[^A-Za-z0-9/._-]")


@dataclass(frozen=True)
class ManyRoute:
    method: str
    template: str
    audience: str
    permission: str | None = None
    staff_only: bool = False

    @property
    def segments(self) -> tuple[str, ...]:
        return tuple(self.template.strip("/").split("/"))


def _r(method: str, template: str, permission: str, *, staff: bool = False) -> ManyRoute:
    return ManyRoute(method, template, ORG, permission, staff)


def _g(method: str, template: str) -> ManyRoute:
    return ManyRoute(method, template, GLOBAL, None, True)


_WA = "/whatsapp"
_FB = "/facebook"
_ACC = "/accounts/{account_id}"
_PAGE = "/accounts/{page_id}"

ROUTES: Final[tuple[ManyRoute, ...]] = (
    # --- WhatsApp accounts ------------------------------------------------------------
    _r("GET", f"{_WA}/connect/start", "channels.connect"),
    _r("POST", f"{_WA}/connect/callback", "channels.connect"),
    _r("GET", f"{_WA}/accounts", "channels.read"),
    _r("GET", f"{_WA}{_ACC}", "channels.read"),
    _r("PATCH", f"{_WA}{_ACC}/ai-settings", "channels.connect"),
    _r("DELETE", f"{_WA}{_ACC}", "channels.disconnect"),
    _r("DELETE", f"{_WA}{_ACC}/hard", "channels.hard_delete"),
    _r("GET", f"{_WA}/accounts/{{channel_id}}/saas-delegation", "channels.connect"),
    _r("PATCH", f"{_WA}/accounts/{{channel_id}}/saas-delegation", "channels.connect"),
    _r("POST", f"{_WA}/accounts/{{channel_id}}/saas-delegation/retry-failed", "channels.connect"),
    # --- WhatsApp outreach (Many needs workspace Owner or Admin for reads too) --------
    _r("GET", f"{_WA}/contacts", "campaigns.run"),
    _r("GET", f"{_WA}/contacts/{{contact_id}}", "campaigns.run"),
    _r("POST", f"{_WA}/contacts/import", "campaigns.run"),
    _r("POST", f"{_WA}/contacts/{{contact_id}}/grant", "campaigns.run"),
    _r("POST", f"{_WA}/contacts/{{contact_id}}/revoke", "campaigns.run"),
    _r("GET", f"{_WA}/templates", "templates.manage"),
    _r("POST", f"{_WA}/templates", "templates.manage"),
    _r("GET", f"{_WA}/templates/{{template_id}}", "templates.manage"),
    _r("PATCH", f"{_WA}/templates/{{template_id}}", "templates.manage"),
    _r("DELETE", f"{_WA}/templates/{{template_id}}", "templates.manage"),
    _r("POST", f"{_WA}/templates/{{template_id}}/submit", "templates.manage"),
    _r("POST", f"{_WA}/templates/{{template_id}}/preview", "templates.manage"),
    _r("POST", f"{_WA}/templates/{{template_id}}/test-send", "templates.manage"),
    _r("POST", f"{_WA}{_ACC}/templates/sync", "templates.manage"),
    _r("GET", f"{_WA}/campaigns", "campaigns.run"),
    _r("POST", f"{_WA}/campaigns", "campaigns.run"),
    _r("GET", f"{_WA}/campaigns/{{campaign_id}}", "campaigns.run"),
    _r("PATCH", f"{_WA}/campaigns/{{campaign_id}}", "campaigns.run"),
    _r("GET", f"{_WA}/campaigns/{{campaign_id}}/stats", "campaigns.run"),
    _r("POST", f"{_WA}/campaigns/{{campaign_id}}/dry-run", "campaigns.run"),
    _r("POST", f"{_WA}/campaigns/{{campaign_id}}/start", "campaigns.run"),
    _r("POST", f"{_WA}/campaigns/{{campaign_id}}/pause", "campaigns.run"),
    _r("POST", f"{_WA}/campaigns/{{campaign_id}}/resume", "campaigns.run"),
    _r("POST", f"{_WA}/campaigns/{{campaign_id}}/cancel", "campaigns.run"),
    _r("GET", f"{_WA}{_ACC}/outreach-health", "campaigns.run"),
    _r("POST", f"{_WA}{_ACC}/health-refresh", "campaigns.run"),
    _r("PATCH", f"{_WA}{_ACC}/outreach-settings", "campaigns.run"),
    _r("POST", f"{_WA}{_ACC}/opt-in-link", "campaigns.run"),
    # --- Facebook ------------------------------------------------------------------------
    _r("GET", f"{_FB}/connect/start", "channels.connect"),
    _r("POST", f"{_FB}/connect/callback", "channels.connect"),
    _r("GET", f"{_FB}/accounts", "channels.read"),
    _r("GET", f"{_FB}{_PAGE}", "channels.read"),
    _r("PATCH", f"{_FB}{_PAGE}/ai-settings", "channels.connect"),
    _r("DELETE", f"{_FB}{_PAGE}", "channels.disconnect"),
    _r("DELETE", f"{_FB}{_PAGE}/hard", "channels.hard_delete"),
    _r("GET", f"{_FB}/accounts/{{channel_id}}/saas-delegation", "channels.connect"),
    _r("PATCH", f"{_FB}/accounts/{{channel_id}}/saas-delegation", "channels.connect"),
    _r("POST", f"{_FB}/accounts/{{channel_id}}/saas-delegation/retry-failed", "channels.connect"),
    _r("GET", f"{_FB}/campaigns", "campaigns.read"),
    _r("POST", f"{_FB}/campaigns", "campaigns.manage"),
    _r("GET", f"{_FB}/campaigns/{{campaign_id}}", "campaigns.read"),
    _r("PATCH", f"{_FB}/campaigns/{{campaign_id}}", "campaigns.manage"),
    _r("DELETE", f"{_FB}/campaigns/{{campaign_id}}", "campaigns.run"),
    _r("POST", f"{_FB}/campaigns/{{campaign_id}}/keywords", "campaigns.manage"),
    _r("DELETE", f"{_FB}/campaigns/{{campaign_id}}/keywords/{{keyword_id}}", "campaigns.manage"),
    # --- Instagram routes that are workspace-scoped in Many: staff only ---------------------
    _r("GET", "/meta/connect/start", "channels.connect", staff=True),
    _r("POST", "/instagram/accounts/{account_id}/reconnect", "channels.connect", staff=True),
    _r("DELETE", "/instagram/accounts/{account_id}/hard", "channels.hard_delete", staff=True),
    # --- Global Many routes (no workspace filter): platform staff only -----------------------
    _g("GET", "/stats/overview"),
    _g("GET", "/logs"),
    _g("GET", "/leads"),
    _g("GET", "/instagram/accounts"),
    _g("GET", "/instagram/accounts/{account_id}"),
    _g("PATCH", "/instagram/accounts/{account_id}/ai-settings"),
    _g("DELETE", "/instagram/accounts/{account_id}"),
    _g("GET", "/instagram/accounts/{account_id}/health"),
    _g("GET", "/instagram/accounts/{account_id}/media"),
    _g("GET", "/instagram/accounts/{channel_id}/saas-delegation"),
    _g("PATCH", "/instagram/accounts/{channel_id}/saas-delegation"),
    _g("POST", "/instagram/accounts/{channel_id}/saas-delegation/retry-failed"),
    _g("GET", "/campaigns"),
    _g("POST", "/campaigns"),
    _g("GET", "/campaigns/{campaign_id}"),
    _g("PATCH", "/campaigns/{campaign_id}"),
    _g("DELETE", "/campaigns/{campaign_id}"),
    _g("POST", "/campaigns/{campaign_id}/activate"),
    _g("POST", "/campaigns/{campaign_id}/pause"),
    _g("POST", "/campaigns/{campaign_id}/archive"),
    _g("POST", "/campaigns/{campaign_id}/unarchive"),
    _g("POST", "/campaigns/{campaign_id}/simulate"),
    _g("GET", "/campaigns/{campaign_id}/keywords"),
    _g("POST", "/campaigns/{campaign_id}/keywords"),
    _g("DELETE", "/campaigns/{campaign_id}/keywords/{keyword_id}"),
    _g("GET", "/campaigns/{campaign_id}/stats"),
    _g("GET", "/conversations"),
    _g("GET", "/conversations/{conversation_id}"),
    _g("POST", "/conversations/{conversation_id}/take-over"),
    _g("POST", "/conversations/{conversation_id}/resume-bot"),
    _g("GET", "/messages"),
    _g("GET", "/messages/{message_id}"),
    _g("POST", "/messages/{message_id}/retry"),
)

# Prefixes that must never be reachable, whatever the table says (checked by the tests).
NEVER_PREFIXES: Final[tuple[str, ...]] = (
    "/api/saas",
    "/saas",
    "/webhooks",
    "/auth",
    "/meta/callback",
    "/meta/compliance",
    "/meta/data-deletion",
    "/health",
    "/privacy",
    "/public",
    "/connections",
)


def normalize(path: str) -> tuple[str, ...] | None:
    """Split a forwarded path into segments, or None if it is not a plain, safe path."""
    if not path or path.startswith("/") or path.endswith("/") or "//" in path:
        return None
    if _UNSAFE.search(path):
        return None
    segments = tuple(path.split("/"))
    if any(segment in ("", ".", "..") or not _SEGMENT.match(segment) for segment in segments):
        return None
    return segments


def match(method: str, path: str, audience: str) -> ManyRoute | None:
    """The one allowlist entry for this call, or None (the proxy then answers 404)."""
    segments = normalize(path)
    if segments is None:
        return None
    method = method.upper()
    best: ManyRoute | None = None
    for route in ROUTES:
        if route.method != method or route.audience != audience:
            continue
        template = route.segments
        if len(template) != len(segments):
            continue
        if all(
            _PARAM.match(t) is not None or t == s for t, s in zip(template, segments, strict=True)
        ):
            # A literal segment beats a parameter at the same position ("import" over {id}).
            literal_count = sum(1 for t in template if _PARAM.match(t) is None)
            if best is None or literal_count > sum(
                1 for t in best.segments if _PARAM.match(t) is None
            ):
                best = route
    return best
