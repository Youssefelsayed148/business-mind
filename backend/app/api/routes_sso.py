"""POST /auth/sso/exchange: trade a SaaS-signed assertion for a short Many token.

Flag off (SSO_ASSERTION_ENABLED=false) answers exactly like an unknown route
(404 {"detail":"Not Found"}) before reading the request. Failures answer one
generic message; the machine-readable reason goes to the audit log only.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_sso_access_token
from app.db.session import get_db
from app.services.audit_service import write_audit_log
from app.services.rate_limit_service import get_client_ip
from app.services.sso_assertion import SSOAssertionError, verify_assertion
from app.services.sso_session import sync_shadow_user

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_ASSERTION_CHARS = 4096


def _fail(db: Session, request: Request, reason: str, code: int) -> HTTPException:
    db.rollback()
    write_audit_log(
        db,
        "sso_exchange_failed",
        "SSO exchange refused",
        entity_type="user",
        severity="warning",
        metadata={"reason": reason, "ip": get_client_ip(request)},
    )
    detail = "Invalid assertion" if code == status.HTTP_401_UNAUTHORIZED else "Service unavailable"
    return HTTPException(status_code=code, detail=detail)


@router.post("/auth/sso/exchange")
async def sso_exchange(request: Request, db: Session = Depends(get_db)):
    if not settings.SSO_ASSERTION_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    try:
        body = await request.json()
        assertion = body.get("assertion") if isinstance(body, dict) else None
    except ValueError:
        assertion = None
    if not isinstance(assertion, str) or not assertion or len(assertion) > MAX_ASSERTION_CHARS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="assertion is required")

    try:
        claims = verify_assertion(assertion)
        user = sync_shadow_user(db, claims)
    except SSOAssertionError as exc:
        unavailable = exc.reason == "replay_store_unavailable"
        raise _fail(db, request, exc.reason, 503 if unavailable else 401)

    token = create_sso_access_token(str(user.id), claims.scope, str(claims.workspace) if claims.workspace else None)
    write_audit_log(
        db,
        "sso_exchange_succeeded",
        f"{user.email} signed in through SSO",
        actor=user,
        entity_type="user",
        entity_id=user.id,
        entity_name=user.email,
        metadata={
            "scope": claims.scope,
            "org": str(claims.org) if claims.org else None,
            "workspace": str(claims.workspace) if claims.workspace else None,
            "role": claims.role,
            "via_agency": claims.via_agency,
            "mfa": claims.mfa,
            "ip": get_client_ip(request),
        },
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.SSO_TOKEN_MINUTES * 60,
        "scope": claims.scope,
        "workspace_id": str(claims.workspace) if claims.workspace else None,
    }
