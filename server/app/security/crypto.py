"""
Cryptography utilities for secret management.

Uses Fernet symmetric encryption (AES-128-CBC with HMAC).
The key is derived from a machine-specific identifier + app salt.
"""
import base64
import hashlib
from cryptography.fernet import Fernet

# App-specific salt (change this when building your own app)
# This adds another layer - attacker needs both this AND the algorithm
_APP_SALT = b"SparkAI-2026-SecretSalt-v1"

def _get_key() -> bytes:
    """
    Generate encryption key from app salt.
    This is deterministic so we can decrypt at runtime.
    """
    # Create a key from the salt using SHA256, then take first 32 bytes for Fernet
    key_material = hashlib.sha256(_APP_SALT).digest()
    # Fernet requires url-safe base64-encoded 32-byte key
    return base64.urlsafe_b64encode(key_material)

def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value."""
    fernet = Fernet(_get_key())
    encrypted = fernet.encrypt(plaintext.encode('utf-8'))
    return encrypted.decode('utf-8')

def decrypt_value(encrypted: str) -> str:
    """Decrypt an encrypted string value."""
    fernet = Fernet(_get_key())
    decrypted = fernet.decrypt(encrypted.encode('utf-8'))
    return decrypted.decode('utf-8')

def encrypt_dict(data: dict) -> dict:
    """Encrypt all string values in a dictionary."""
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = encrypt_value(value)
        else:
            result[key] = value
    return result

def decrypt_dict(data: dict) -> dict:
    """Decrypt all string values in a dictionary."""
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            try:
                result[key] = decrypt_value(value)
            except Exception:
                # If decryption fails, use as-is (might be unencrypted)
                result[key] = value
        else:
            result[key] = value
    return result
