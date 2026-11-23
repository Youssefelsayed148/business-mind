from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.security import create_access_token, decode_access_token, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import MeResponse, TokenResponse
from app.roles import normalize_role
from app.services.audit_service import write_audit_log
from app.services.rate_limit_service import check_login_rate_limits, get_client_ip, raise_rate_limited

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except Exception:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    limited = check_login_rate_limits(request, form_data.username)
    if limited:
        result, window_name = limited
        write_audit_log(
            db,
            "login_rate_limited",
            f"Login rate limited for {form_data.username}",
            actor_email=form_data.username,
            entity_type="user",
            severity="warning",
            metadata={"ip": get_client_ip(request), "path": str(request.url.path), "window": window_name},
        )
        raise_rate_limited(result, "Too many login attempts. Please try again later.")

    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        write_audit_log(
            db,
            "login_failed",
            f"Failed login attempt for {form_data.username}",
            actor_email=form_data.username,
            entity_type="user",
            severity="warning",
            metadata={"reason": "invalid_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user.role = normalize_role(user.role)
    db.commit()
    write_audit_log(
        db,
        "login_success",
        f"{user.email} logged in",
        actor=user,
        entity_type="user",
        entity_id=user.id,
        entity_name=user.email,
        severity="info",
    )
    access_token = create_access_token(subject=str(user.id))
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/auth/me", response_model=MeResponse)
async def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "role": normalize_role(current_user.role),
    }


@router.post("/auth/logout")
async def logout():
    return {"status": "ok"}
