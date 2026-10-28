"""Meta-signed callback intake and an opaque public deletion receipt page."""
import re
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.data_deletion_request import DataDeletionRequest
from app.services.meta_compliance import MAX_SIGNED_REQUEST, InvalidSignedRequest, receive_callback

router = APIRouter()
_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow"}


async def _signed_form(request: Request) -> str:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=403, detail="Invalid callback")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_SIGNED_REQUEST + 128:
            raise HTTPException(status_code=413, detail="Callback too large")
        body.extend(chunk)
    try:
        data = parse_qs(body.decode("ascii"), strict_parsing=True, max_num_fields=4)
        values = data.get("signed_request", [])
        if len(values) != 1 or not values[0] or set(data) != {"signed_request"}:
            raise ValueError()
        return values[0]
    except (ValueError, UnicodeError):
        raise HTTPException(status_code=403, detail="Invalid callback") from None


def _base_url() -> str:
    base = settings.APP_BASE_URL.rstrip("/")
    parts = urlsplit(base)
    if (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
            or parts.scheme not in ("http", "https")
            or (settings.APP_ENV == "production" and parts.scheme != "https")):
        raise HTTPException(status_code=503, detail="Callback service unavailable")
    return base


@router.post("/meta/compliance/{app}/deauthorize")
async def deauthorize(app: str, request: Request, db: Session = Depends(get_db)):
    if app not in ("instagram", "facebook"):
        raise HTTPException(status_code=404)
    value = await _signed_form(request)
    try:
        receive_callback(db, app=app, kind="deauthorize", signed_request=value)
        db.commit()
    except InvalidSignedRequest:
        raise HTTPException(status_code=403, detail="Invalid callback") from None
    return JSONResponse({"status": "received"}, headers=_HEADERS)


@router.post("/meta/compliance/{app}/data-deletion")
async def data_deletion(app: str, request: Request, db: Session = Depends(get_db)):
    if app not in ("instagram", "facebook"):
        raise HTTPException(status_code=404)
    base = _base_url()
    value = await _signed_form(request)
    try:
        row = receive_callback(db, app=app, kind="deletion", signed_request=value)
        code = row.confirmation_code
        db.commit()
    except InvalidSignedRequest:
        raise HTTPException(status_code=403, detail="Invalid callback") from None
    return JSONResponse({"url": f"{base}/meta/data-deletion/status/{code}", "confirmation_code": code}, headers=_HEADERS)


@router.get("/meta/data-deletion/status/{code}", response_class=HTMLResponse)
async def deletion_status(code: str, db: Session = Depends(get_db)):
    row = None
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", code):
        row = db.query(DataDeletionRequest).filter(DataDeletionRequest.confirmation_code == code).one_or_none()
    if row is None:
        return HTMLResponse("<!doctype html><html lang='en'><title>Deletion request</title><h1>Request unavailable</h1></html>", status_code=404, headers=_HEADERS)
    text = ("Deletion completed after operator verification." if row.status == "completed"
            else "Request received. Operator review and deletion are pending. Receipt does not mean deletion is complete.")
    return HTMLResponse("<!doctype html><html lang='en'><meta name='viewport' content='width=device-width'><title>Deletion request</title><main><h1>Deletion request</h1><p>" + text + "</p><p>For help contact privacy@theosirislabs.com.</p></main></html>", headers=_HEADERS)
