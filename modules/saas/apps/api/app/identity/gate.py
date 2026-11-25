"""Flag gate shared by every identity-v2 route: flag off answers like an unknown route."""

from typing import Annotated

from fastapi import Depends
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings, get_settings


def identity_v2_only(settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """404 {"detail":"Not Found"} while IDENTITY_V2_ENABLED is off, before auth or validation."""
    if not settings.identity_v2_enabled:
        raise StarletteHTTPException(status_code=404, detail="Not Found")


IdentityV2On = Annotated[None, Depends(identity_v2_only)]
