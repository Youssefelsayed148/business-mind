"""Built-in organization roles and the permission table (design section 5).

One table in code, no per-organization custom roles. ``editor`` is the stored
legacy name of the Agent role: ``LEGACY_TO_ORG_ROLE`` is the only mapping and
it never escalates (viewer, editor to agent, admin).
"""

from typing import Final

ORG_ROLES: Final[tuple[str, ...]] = ("owner", "admin", "manager", "agent", "viewer")
LEGACY_TO_ORG_ROLE: Final[dict[str, str]] = {
    "viewer": "viewer",
    "editor": "agent",
    "admin": "admin",
}
# Roles an agency grant may cap at; never Owner (design 4.3).
GRANT_ROLE_CAPS: Final[tuple[str, ...]] = ("admin", "manager", "agent", "viewer")
# Permission families an agency person never holds, whatever the cap is.
AGENCY_FORBIDDEN_PREFIXES: Final[tuple[str, ...]] = ("team.", "agency.", "billing.", "org.")

_READ = frozenset(
    {
        "inbox.read",
        "contacts.read",
        "analytics.read",
        "channels.read",
        "knowledge.read",
        "campaigns.read",
        "bots.read",
        "org.read",
    }
)
_AGENT = _READ | {"inbox.reply", "contacts.write"}
_MANAGER = _AGENT | {"knowledge.write", "campaigns.manage"}
_ADMIN = _MANAGER | {
    "contacts.delete",
    "contacts.merge",
    "contacts.stages",
    "conversations.delete",
    "contacts.export",
    "analytics.export",
    "data.export",
    "campaigns.run",
    "templates.manage",
    "channels.connect",
    "channels.disconnect",
    "team.read",
    "team.manage",
    "agency.view",
    "audit.view",
    "data.erase",
    "org.settings",
}
_OWNER = _ADMIN | {
    "channels.hard_delete",
    "team.manage_admins",
    "agency.manage",
    "billing.view",
    "billing.manage",
}
STAFF_ONLY_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {"bots.configure", "rag.settings", "org.delete"}
)

ROLE_PERMISSIONS: Final[dict[str, frozenset[str]]] = {
    "viewer": frozenset(_READ),
    "agent": frozenset(_AGENT),
    "manager": frozenset(_MANAGER),
    "admin": frozenset(_ADMIN),
    "owner": frozenset(_OWNER),
}
ALL_PERMISSIONS: Final[frozenset[str]] = _OWNER | STAFF_ONLY_PERMISSIONS
# Platform staff hold every permission (a flag on the user, never a role).
STAFF_PERMISSIONS: Final[frozenset[str]] = ALL_PERMISSIONS


def org_role_of(legacy_role: str, org_role: str | None) -> str:
    """The effective role: the explicit org_role, else the mapped legacy role."""
    if org_role is not None:
        if org_role not in ORG_ROLES:
            raise ValueError(f"unknown organization role: {org_role!r}")
        return org_role
    try:
        return LEGACY_TO_ORG_ROLE[legacy_role]
    except KeyError:
        raise ValueError(f"unknown legacy role: {legacy_role!r}") from None


def permissions_for_role(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS[role]


def agency_permissions(role_cap: str) -> frozenset[str]:
    """What an agency person holds: the cap's permissions minus team/agency/billing/org."""
    if role_cap not in GRANT_ROLE_CAPS:
        raise ValueError(f"invalid agency role cap: {role_cap!r}")
    return frozenset(
        p
        for p in ROLE_PERMISSIONS[role_cap]
        if not any(p.startswith(prefix) for prefix in AGENCY_FORBIDDEN_PREFIXES)
    )
