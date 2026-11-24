"""Flatten the FastAPI route table (including lazily included routers) for classification tests."""
import re
import uuid
from dataclasses import dataclass

from fastapi.routing import APIRoute


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str  # full template as served, e.g. /whatsapp/accounts/{account_id}
    uses_user: bool  # get_current_user is somewhere in its dependency tree
    workspace_scoped: bool  # a workspace-scoped authz dependency is in the tree
    module: str


def _walk(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _walk(dep)


def _flatten(routes):
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            for ctx in contexts():
                yield ctx.original_route, ctx.path
        else:
            yield route, getattr(route, "path", "")


def inventory(app) -> list[RouteInfo]:
    from app.api.routes_auth import get_current_user

    found = []
    for route, path in _flatten(app.routes):
        if not isinstance(route, APIRoute):
            for method in ("GET",):
                found.append(RouteInfo(method, path, False, False, "starlette"))
            continue
        calls = list(_walk(route.dependant))
        uses_user = get_current_user in calls
        ws = any(
            getattr(c, "__module__", "") == "app.authz" and "workspace" in getattr(c, "__qualname__", "")
            for c in calls
        )
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            found.append(RouteInfo(method, path, uses_user, ws, route.endpoint.__module__))
    return found


def concrete(path: str) -> str:
    """Fill path parameters with a well-formed dummy so requests reach the dependencies."""
    return re.sub(r"\{[^}]+\}", lambda _m: str(uuid.uuid4()), path)
