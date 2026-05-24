"""
Shared Fernet encryption for OAuth refresh tokens.

All token encrypt/decrypt goes through here — services never do their own crypto.

Generate a key once:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
Store the result in TOKEN_ENCRYPTION_KEY in your .env — never hardcode it.
"""

import os
import logging
from typing import Optional
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.getenv("TOKEN_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY not set in environment")
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt_token(plain: str) -> str:
    """Encrypt plaintext token → Fernet ciphertext string."""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_token(cipher: str) -> str:
    """Decrypt Fernet ciphertext → plaintext token string."""
    return _get_fernet().decrypt(cipher.encode()).decode()
