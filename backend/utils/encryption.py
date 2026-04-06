"""
Fernet-based column encryption for SQLAlchemy.

Provides an EncryptedText TypeDecorator that transparently encrypts on write
and decrypts on read. Requires ZPAY_ENCRYPTION_KEY env var (Fernet key).

Generate a key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import os
import logging
from sqlalchemy import TypeDecorator, Text

logger = logging.getLogger("zpay.encryption")

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.environ.get("ZPAY_ENCRYPTION_KEY", "")
    if not key:
        logger.warning("ZPAY_ENCRYPTION_KEY not set — PII columns will NOT be encrypted")
        return None
    from cryptography.fernet import Fernet
    try:
        _fernet = Fernet(key.encode("utf-8"))
        return _fernet
    except Exception as e:
        logger.error("Invalid ZPAY_ENCRYPTION_KEY: %s", e)
        return None


class EncryptedText(TypeDecorator):
    """SQLAlchemy type that encrypts/decrypts text using Fernet.

    Falls back to plaintext storage if ZPAY_ENCRYPTION_KEY is not configured,
    allowing graceful degradation during development.
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        f = _get_fernet()
        if f is None:
            return value  # no encryption key — store plaintext
        return f.encrypt(value.encode("utf-8")).decode("utf-8")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        f = _get_fernet()
        if f is None:
            return value
        try:
            return f.decrypt(value.encode("utf-8")).decode("utf-8")
        except Exception:
            # Value might be unencrypted (pre-migration data)
            return value
