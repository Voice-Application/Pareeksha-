"""Web sign-in accounts, called only by the Next.js server with an admin key."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from pareeksha.api.auth import AdminKey
from pareeksha.api.deps import AUTH_ERRORS, Db, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.passwords import MAX_LENGTH, MIN_LENGTH, hash_password, verify_password
from pareeksha.db.models import Users

router = APIRouter(tags=["users"], responses=AUTH_ERRORS)

Role = Literal["admin", "member"]
_EMAIL = r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$"
_LOCK_KEY = 0x70617265  # pg_advisory_xact_lock key shared by bootstrap and user updates
_DUMMY_HASH = hash_password("dummy-password-for-timing")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserOut(BaseModel):
    id: UUID
    email: str
    name: str
    role: Role
    disabled: bool
    created_at: datetime
    last_login_at: datetime | None


class UserList(BaseModel):
    items: list[UserOut]


class AuthStatus(BaseModel):
    has_users: bool


class BootstrapIn(_Body):
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254, pattern=_EMAIL)]
    name: str = Field(min_length=1, max_length=200)
    password: str


class LoginIn(_Body):
    email: str = Field(max_length=254)
    password: str = Field(max_length=1000)


class UserCreate(BootstrapIn):
    role: Role


class UserPatch(_Body):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    disabled: bool | None = None
    password: str | None = None


def _out(row: Users) -> UserOut:
    return UserOut(
        id=row.id,
        email=row.email,
        name=row.name,
        role=row.role,  # type: ignore[arg-type]
        disabled=row.disabled_at is not None,
        created_at=row.created_at,
        last_login_at=row.last_login_at,
    )


def _check_password(password: str) -> None:
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise ApiError(
            422, "invalid_password", f"Password must be {MIN_LENGTH} to {MAX_LENGTH} characters"
        )


def _norm(email: str) -> str:
    return email.strip().lower()


async def _lock(session: Db) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})


async def _insert(session: Db, body: BootstrapIn, role: Role) -> Users:
    _check_password(body.password)
    row = Users(
        email=_norm(body.email),
        name=body.name.strip(),
        password_hash=await asyncio.to_thread(hash_password, body.password),
        role=role,
    )
    session.add(row)
    try:
        await session.flush()
        await session.refresh(row)
    except IntegrityError as exc:
        raise ApiError(409, "email_taken", "A user with this email already exists") from exc
    return row


@router.get("/auth/status", summary="Whether any user exists yet")
async def auth_status(key: AdminKey, session: Db) -> AuthStatus:
    count = await session.scalar(select(func.count()).select_from(Users))
    return AuthStatus(has_users=bool(count))


@router.post(
    "/auth/bootstrap",
    status_code=201,
    responses=errors(409, 422),
    summary="Create the first admin user (409 once any user exists)",
)
async def bootstrap(body: BootstrapIn, key: AdminKey, session: Db) -> UserOut:
    await _lock(session)
    if await session.scalar(select(func.count()).select_from(Users)):
        raise ApiError(409, "already_bootstrapped", "A user already exists")
    return _out(await _insert(session, body, "admin"))


@router.post(
    "/auth/login",
    responses=errors(401, 403),
    summary="Verify credentials; the web tier creates the session",
)
async def login(body: LoginIn, key: AdminKey, session: Db) -> UserOut:
    row = await session.scalar(select(Users).where(Users.email == _norm(body.email)))
    stored = row.password_hash if row else _DUMMY_HASH
    ok = await asyncio.to_thread(verify_password, body.password, stored)
    if row is None or not ok:
        raise ApiError(401, "invalid_credentials", "Invalid email or password")
    if row.disabled_at is not None:
        raise ApiError(403, "account_disabled", "This account is disabled")
    row.last_login_at = datetime.now(UTC)
    await session.flush()
    return _out(row)


@router.get("/users", summary="List users")
async def list_users(key: AdminKey, session: Db) -> UserList:
    rows = (await session.scalars(select(Users).order_by(Users.created_at, Users.id))).all()
    return UserList(items=[_out(r) for r in rows])


@router.post("/users", status_code=201, responses=errors(409, 422), summary="Create a user")
async def create_user(body: UserCreate, key: AdminKey, session: Db) -> UserOut:
    return _out(await _insert(session, body, body.role))


@router.patch(
    "/users/{user_id}",
    responses=errors(404, 409, 422),
    summary="Update name, role, disabled flag or password",
)
async def update_user(user_id: UUID, body: UserPatch, key: AdminKey, session: Db) -> UserOut:
    await _lock(session)
    row = await session.get(Users, user_id)
    if row is None:
        raise ApiError(404, "not_found", "User not found")
    new_role = body.role or row.role
    new_disabled = row.disabled_at is not None if body.disabled is None else body.disabled
    if row.role == "admin" and row.disabled_at is None and (new_role != "admin" or new_disabled):
        others = await session.scalar(
            select(func.count())
            .select_from(Users)
            .where(Users.role == "admin", Users.disabled_at.is_(None), Users.id != row.id)
        )
        if not others:
            raise ApiError(409, "last_admin", "Cannot remove or disable the last active admin")
    if body.password is not None:
        _check_password(body.password)
        row.password_hash = await asyncio.to_thread(hash_password, body.password)
    if body.name is not None:
        row.name = body.name.strip()
    row.role = new_role
    if new_disabled != (row.disabled_at is not None):
        row.disabled_at = datetime.now(UTC) if new_disabled else None
    await session.flush()
    return _out(row)
