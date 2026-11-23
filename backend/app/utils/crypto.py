from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = settings.TOKEN_ENCRYPTION_KEY
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not configured")
    _fernet = Fernet(key.encode("utf-8"))
    return _fernet


def encrypt_text(plain_text: str) -> str:
    f = _get_fernet()
    return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_text(encrypted_text: str) -> str:
    f = _get_fernet()
    try:
        return f.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Invalid or corrupted encrypted token") from exc
