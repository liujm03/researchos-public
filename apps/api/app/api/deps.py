from dataclasses import dataclass

from fastapi import Cookie, Depends, Header
from sqlalchemy.orm import Session

from app.core.security import csrf_for_token, secure_compare
from app.db import get_db
from app.errors import DomainError
from app.models import User, UserSession
from app.services.auth import get_session


@dataclass
class AuthContext:
    user: User
    session: UserSession
    raw_token: str


def current_context(
    db: Session = Depends(get_db),
    researchos_session: str | None = Cookie(default=None),
) -> AuthContext:
    result = get_session(db, researchos_session)
    if result is None or researchos_session is None:
        raise DomainError("UNAUTHORIZED", "Sign in required", 401)
    user, session = result
    return AuthContext(user=user, session=session, raw_token=researchos_session)


def csrf_context(
    context: AuthContext = Depends(current_context),
    x_csrf_token: str | None = Header(default=None),
) -> AuthContext:
    if x_csrf_token is None or not secure_compare(x_csrf_token, csrf_for_token(context.raw_token)):
        raise DomainError("FORBIDDEN", "CSRF token missing or invalid", 403)
    return context
