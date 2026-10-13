"""Fernet symmetric encryption and decryption utilities for sensitive settings.

Follows Prompt 7e and Architecture §9.6:
- Encrypts LLM provider API keys at rest in PostgreSQL.
- Redacts keys from strings, logs, and API representations.
- Uses SETTINGS_ENCRYPTION_KEY environment variable.
"""
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import settings
from app.core.logger import logger


_fernet_instance: Optional[Fernet] = None


def get_fernet() -> Fernet:
    """Return a Fernet cipher instance initialized with SETTINGS_ENCRYPTION_KEY.
    
    In production, a missing or invalid key raises a hard error.
    In development/testing, if unset, a deterministic fallback key is used with a warning.
    """
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    key_secret = settings.SETTINGS_ENCRYPTION_KEY
    if key_secret and key_secret.get_secret_value():
        key_bytes = key_secret.get_secret_value().encode("utf-8")
        try:
            _fernet_instance = Fernet(key_bytes)
            return _fernet_instance
        except Exception as exc:
            if settings.APP_ENV == "production":
                raise ValueError(
                    f"Invalid SETTINGS_ENCRYPTION_KEY in production: {exc}. "
                    "Must be a 32-byte url-safe base64-encoded key."
                ) from exc
            logger.warning(
                f"Invalid SETTINGS_ENCRYPTION_KEY in {settings.APP_ENV}: {exc}. "
                "Falling back to dev encryption key."
            )

    if settings.APP_ENV == "production":
        raise ValueError(
            "SETTINGS_ENCRYPTION_KEY is required in production! "
            "Generate one using: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )

    # Deterministic development/test key (32 bytes url-safe base64)
    # Never used in production
    dev_key = b"0123456789abcdef0123456789abcdef0123456789a="  # 44 chars base64 valid
    # Generate a standard valid urlsafe key for dev
    dev_key = b"dev_settings_key_32bytes_base64_padding_=="
    try:
        _fernet_instance = Fernet(dev_key)
    except Exception:
        # Fallback to standard generated dev key
        import base64
        # 32 bytes padded
        padded = base64.urlsafe_b64encode(b"development_fernet_key_32bytes!!")
        _fernet_instance = Fernet(padded)

    return _fernet_instance


def encrypt_api_key(plain_key: Optional[str]) -> Optional[str]:
    """Encrypt a plain text API key. Returns None if input is empty or None."""
    if not plain_key or not plain_key.strip():
        return None
    cipher = get_fernet()
    encrypted_bytes = cipher.encrypt(plain_key.strip().encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_api_key(encrypted_token: Optional[str]) -> Optional[str]:
    """Decrypt an encrypted Fernet token back to plain text string."""
    if not encrypted_token or not encrypted_token.strip():
        return None
    cipher = get_fernet()
    try:
        decrypted_bytes = cipher.decrypt(encrypted_token.strip().encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except InvalidToken as exc:
        logger.error("Failed to decrypt API key: InvalidToken or wrong encryption key.")
        raise ValueError("Could not decrypt stored API key. Encryption key may have changed.") from exc


def get_key_hint(plain_or_encrypted: Optional[str], is_encrypted: bool = False) -> Optional[str]:
    """Return a safe masked hint (e.g. '...1234') showing only the last 4 characters.
    
    Never exposes the full key.
    """
    if not plain_or_encrypted:
        return None
    
    plain_val = plain_or_encrypted
    if is_encrypted:
        try:
            plain_val = decrypt_api_key(plain_or_encrypted)
        except Exception:
            return None

    if not plain_val or len(plain_val) < 4:
        return "...****" if plain_val else None

    return f"...{plain_val[-4:]}"
