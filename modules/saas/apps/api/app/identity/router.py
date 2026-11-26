"""SSO issuing routes (design 2.1). Flag off (SSO_ISSUER_ENABLED): 404 before anything else."""

import re
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as OrmSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import cookies
from app.auth.security import hash_token
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.models import User
from app.db.session import get_session
from app.identity.sso import mint_assertion

router = APIRouter(prefix="/api/v1/sso", tags=["sso"])

DbSession = Annotated[OrmSession, Depends(get_session)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]
STATE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def _issuer_enabled(settings: CurrentSettings) -> None:
    """Answer exactly like an unknown route while the flag is off."""
    if not settings.sso_issuer_enabled:
        raise StarletteHTTPException(status_code=404, detail="Not Found")


IssuerOn = Annotated[None, Depends(_issuer_enabled)]
CurrentUser = Annotated[User, Depends(cookies.get_current_user)]
CsrfOk = Annotated[None, Depends(cookies.require_csrf)]


class AssertionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["client", "staff"] = "client"
    org: UUID | None = None


class AssertionResponse(BaseModel):
    assertion: str
    scope: Literal["client", "staff"]
    workspace_id: UUID | None
    expires_in: int


def _token_hash(request: Request, settings: Settings) -> str | None:
    token = cookies.read_session_token(request, settings)
    return hash_token(token) if token else None


@router.post("/assertions", response_model=AssertionResponse)
def create_assertion(
    _on: IssuerOn,
    body: AssertionRequest,
    request: Request,
    db: DbSession,
    settings: CurrentSettings,
    user: CurrentUser,
    _csrf: CsrfOk,
) -> AssertionResponse:
    """Same-origin callers: cookie + CSRF, the assertion comes back in the body."""
    minted = mint_assertion(
        db,
        settings,
        user,
        scope=body.scope,
        org_id=body.org,
        session_token_hash=_token_hash(request, settings),
    )
    return AssertionResponse(
        assertion=minted.token,
        scope=minted.scope,
        workspace_id=minted.workspace_id,
        expires_in=minted.expires_in,
    )


@router.get("/authorize")
def authorize(
    _on: IssuerOn,
    request: Request,
    db: DbSession,
    settings: CurrentSettings,
    user: CurrentUser,
    state: Annotated[str, Query(max_length=128)],
    return_url: Annotated[str, Query(alias="return", max_length=2000)],
    org: UUID | None = None,
    scope: Literal["client", "staff"] = "client",
) -> RedirectResponse:
    """Redirect flow for Many's dashboard: the assertion rides in the URL fragment.

    No side effect besides the redirect. `return` must equal an allowlisted callback
    URL exactly and `state` is echoed back for the caller to check (design 10).
    """
    if not STATE_RE.fullmatch(state):
        raise ApiError(422, "VALIDATION_ERROR", "Invalid state.")
    if return_url not in settings.sso_return_allowlist:
        raise ApiError(422, "VALIDATION_ERROR", "Invalid return address.")
    minted = mint_assertion(
        db,
        settings,
        user,
        scope=scope,
        org_id=org,
        session_token_hash=_token_hash(request, settings),
    )
    location = (
        f"{return_url}#assertion={quote(minted.token, safe='')}&state={quote(state, safe='')}"
    )
    return RedirectResponse(
        location,
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
