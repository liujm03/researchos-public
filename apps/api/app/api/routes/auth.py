from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.core.config import get_settings
from app.core.security import csrf_for_token
from app.db import get_db
from app.errors import DomainError
from app.models import User
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["user"])


class SetupRequest(BaseModel):
    setup_token: str
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=1024)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SessionOut(BaseModel):
    id: str
    email: str
    display_name: str
    timezone: str
    csrf_token: str | None


class MePatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)


def user_response(user: User, csrf_token: str | None = None) -> SessionOut:
    return SessionOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        timezone=user.timezone,
        csrf_token=csrf_token,
    )


@router.post("/setup", status_code=201, response_model=SessionOut)
def setup(body: SetupRequest, db: Session = Depends(get_db)) -> SessionOut:
    user = auth_service.setup_user(
        db, body.email, body.display_name, body.password, body.setup_token
    )
    return user_response(user)


@router.get("/setup-state")
def setup_state(db: Session = Depends(get_db)) -> dict[str, bool]:
    return {"needs_setup": not bool(db.scalar(select(func.count()).select_from(User)))}


@router.post("/login", response_model=SessionOut)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> SessionOut:
    user, raw_token = auth_service.login(db, body.email, body.password)
    response.set_cookie(
        "researchos_session",
        raw_token,
        max_age=get_settings().session_ttl_hours * 3600,
        httponly=True,
        secure=get_settings().app_env == "production",
        samesite="lax",
        path="/",
    )
    return user_response(user, csrf_for_token(raw_token))


@router.get("/session", response_model=SessionOut)
def session(context: AuthContext = Depends(current_context)) -> SessionOut:
    return user_response(context.user, csrf_for_token(context.raw_token))


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> None:
    auth_service.logout(db, context.session)
    response.delete_cookie("researchos_session", path="/")


@me_router.get("/me", response_model=SessionOut)
def me(context: AuthContext = Depends(current_context)) -> SessionOut:
    return user_response(context.user, csrf_for_token(context.raw_token))


@me_router.patch("/me", response_model=SessionOut)
def update_me(
    body: MePatch,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> SessionOut:
    changes = body.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise DomainError("VALIDATION_ERROR", "Profile fields cannot be null", 422)
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except ZoneInfoNotFoundError as exc:
            raise DomainError("VALIDATION_ERROR", "Unknown timezone", 422) from exc
    for key, value in changes.items():
        setattr(context.user, key, value)
    db.commit()
    db.refresh(context.user)
    return user_response(context.user, csrf_for_token(context.raw_token))
