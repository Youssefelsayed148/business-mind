import pytest

from app.core.config import settings
from app.utils.crypto import decrypt_text, encrypt_text


def test_encrypt_decrypt_roundtrip():
    plain = "super_secret_token_123"
    encrypted = encrypt_text(plain)
    decrypted = decrypt_text(encrypted)
    assert decrypted == plain


def test_encrypted_output_not_equal_to_plaintext():
    plain = "my_token"
    encrypted = encrypt_text(plain)
    assert encrypted != plain


def test_decrypt_invalid_token_raises():
    with pytest.raises(ValueError, match="Invalid or corrupted encrypted token"):
        decrypt_text("not_a_valid_token")
