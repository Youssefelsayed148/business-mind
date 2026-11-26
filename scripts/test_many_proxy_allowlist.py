"""Cross-check the SaaS proxy allowlist against Many's real routes and guards (Phase 4A, P1).

Run in the Many virtualenv (it imports the Many app; no database is needed to read the route table):
  APP_ENV=test DATABASE_URL=postgresql://x@localhost/x_test JWT_SECRET=throwaway \
  META_APP_SECRET=throwaway META_WEBHOOK_VERIFY_TOKEN=throwaway \
      python -m pytest scripts/test_many_proxy_allowlist.py

It loads the two stdlib-only SaaS modules by path, so the SaaS and Many virtualenvs stay separate.
Checks: every allowlisted call is a real Many route; the SaaS permission lets exactly the roles
through that Many's own workspace guard lets through; global entries sit behind a global guard.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
IDENTITY = ROOT / "modules" / "saas" / "apps" / "api" / "app" / "identity"
sys.path.insert(0, str(ROOT / "backend"))


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"saas_{name}", IDENTITY / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


many_routes = _load("many_routes")
saas_roles = _load("roles")

try:
    from app.authz import ROLE_PERMISSIONS as MANY_PERMISSIONS  # noqa: E402
    from app.main import app as many_app  # noqa: E402
    from app.services.sso_session import ORG_TO_WORKSPACE_ROLE  # noqa: E402
except Exception as exc:  # pragma: no cover
    pytest.skip(f"the Many app cannot be imported here: {exc}", allow_module_level=True)

MANY_ROLES = ("owner", "admin", "operator", "viewer")


def _walk(routes: Any, prefix: str, found: dict[tuple[str, str], Any]) -> None:
    for route in routes:
        context = getattr(route, "include_context", None)
        if context is not None:  # an included router (newer FastAPI keeps it lazy)
            _walk(context.included_router.routes, prefix + (context.prefix or ""), found)
            continue
        for method in getattr(route, "methods", None) or ():
            found[(method, prefix + route.path)] = route


def _real_routes() -> dict[tuple[str, str], Any]:
    found: dict[tuple[str, str], Any] = {}
    _walk(many_app.routes, "", found)
    return found


def _guard_of(route: Any) -> tuple[str, Any]:
    """('role', allowed_set_or_None) | ('permission', name) | ('any_permission', names) | ('global', None)."""
    for dep in route.dependant.dependencies:
        call = dep.call
        name = getattr(call, "__qualname__", "")
        if "require_workspace_role" in name:
            return "role", inspect.getclosurevars(call).nonlocals.get("allowed")
        if "require_workspace_permission" in name:
            return "permission", inspect.getclosurevars(call).nonlocals.get("permission")
        if "require_workspace_any_permission" in name:
            return "any_permission", inspect.getclosurevars(call).nonlocals.get("permissions")
    return "global", None


def _many_allows(guard: tuple[str, Any], many_role: str) -> bool:
    kind, value = guard
    if kind == "role":
        return value is None or many_role in value
    if kind == "permission":
        return value in MANY_PERMISSIONS[many_role]
    if kind == "any_permission":
        return any(p in MANY_PERMISSIONS[many_role] for p in value)
    raise AssertionError(kind)


def test_every_allowlisted_call_is_a_real_many_route() -> None:
    real = _real_routes()
    missing = [
        f"{r.method} {r.template}" for r in many_routes.ROUTES if (r.method, r.template) not in real
    ]
    assert not missing, "\n".join(missing)


def test_the_saas_permission_matches_many_workspace_guard_for_every_role() -> None:
    real = _real_routes()
    differences: list[str] = []
    for route in many_routes.ROUTES:
        if route.audience != many_routes.ORG or route.staff_only:
            continue
        guard = _guard_of(real[(route.method, route.template)])
        assert guard[0] != "global", f"{route.method} {route.template} has no workspace guard in Many"
        for saas_role in saas_roles.ORG_ROLES:
            saas_allows = route.permission in saas_roles.ROLE_PERMISSIONS[saas_role]
            many_allows = _many_allows(guard, ORG_TO_WORKSPACE_ROLE[saas_role])
            if saas_allows != many_allows:
                differences.append(
                    f"{saas_role} {route.method} {route.template}: SaaS {saas_allows}, Many {many_allows}"
                )
    assert not differences, "\n".join(differences)


def test_global_and_staff_only_entries_are_not_open_to_clients_in_many() -> None:
    from app.core.client_scope import client_scope_allows

    for route in many_routes.ROUTES:
        if route.audience == many_routes.GLOBAL or route.staff_only:
            assert not client_scope_allows(route.template, route.template), (
                f"{route.method} {route.template} is staff only here but a client token may call it in Many"
            )


def test_every_client_scoped_entry_is_inside_manys_client_scope() -> None:
    from app.core.client_scope import client_scope_allows

    for route in many_routes.ROUTES:
        if route.audience == many_routes.ORG and not route.staff_only:
            assert client_scope_allows(route.template, route.template), f"{route.method} {route.template}"
