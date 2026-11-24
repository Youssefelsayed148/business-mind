from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode = {"sub": str(subject), "exp": expire, "type": "access"}
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")


def create_sso_access_token(subject: str, scope: str, workspace_id: str | None = None) -> str:
    """Short Many session token minted by the SSO exchange (identity design 2.1).

    Same HS256 format and secret as the legacy token, with type="sso_access"
    plus the scope the client-scope guard reads. `ws` is informational.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.SSO_TOKEN_MINUTES)
    to_encode = {"sub": str(subject), "exp": expire, "type": "sso_access", "scope": scope}
    if workspace_id:
        to_encode["ws"] = str(workspace_id)
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
