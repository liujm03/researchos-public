import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    hash_password,
    hash_token,
    new_session_token,
    secure_compare,
    verify_password,
)
from app.errors import DomainError
from app.models import User, UserSession


def setup_user(db: Session, email: str, display_name: str, password: str, token: str) -> User:
    configured = get_settings().initial_setup_token
    if not configured or not secure_compare(token, configured):
        raise DomainError("FORBIDDEN", "Invalid setup token", 403)
    if db.scalar(select(func.count()).select_from(User)):
        raise DomainError("CONFLICT", "Initial user already exists", 409)
    user = User(
        id=uuid.uuid4(),
        email=email.strip().lower(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        timezone=get_settings().app_timezone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login(db: Session, email: str, password: str) -> tuple[User, str]:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active or not verify_password(user.password_hash, password):
        raise DomainError("UNAUTHORIZED", "Invalid credentials", 401)
    if not get_settings().session_secret or not get_settings().csrf_secret:
        raise DomainError("SERVER_NOT_CONFIGURED", "Session secrets are not configured", 503)
    raw_token = new_session_token()
    db.add(
        UserSession(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(hours=get_settings().session_ttl_hours),
        )
    )
    db.commit()
    return user, raw_token


def get_session(db: Session, raw_token: str | None) -> tuple[User, UserSession] | None:
    if not raw_token:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(raw_token)))
    if session is None or session.revoked_at is not None:
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    return user, session


def logout(db: Session, session: UserSession) -> None:
    session.revoked_at = datetime.now(UTC)
    db.commit()
