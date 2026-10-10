import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_for_token(token: str) -> str:
    secret = get_settings().csrf_secret
    if not secret:
        raise RuntimeError("CSRF_SECRET must be configured")
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), "sha256").hexdigest()


def secure_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
