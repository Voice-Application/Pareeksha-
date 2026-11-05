"""User accounts: bootstrap, login, CRUD and last-admin protection against real Postgres."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.passwords import hash_password, verify_password
from pareeksha.db.models import Users
from tests.conftest import Tenant

PW = "correct horse battery"


def test_hash_roundtrip() -> None:
    stored = hash_password(PW)
    assert stored.startswith("scrypt$32768$8$1$") and PW not in stored
    assert verify_password(PW, stored) and not verify_password("wrong password!", stored)
    assert not verify_password(PW, "garbage") and stored != hash_password(PW)  # salted


async def _clear(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        await session.execute(delete(Users))
        await session.commit()


async def _admin(api: AsyncClient, t: Tenant, email: str = "a@example.com") -> dict[str, object]:
    r = await api.post(
        "/api/v1/users",
        json={"email": email, "name": "A", "password": PW, "role": "admin"},
        headers=t.admin,
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_bootstrap_once_then_409(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _clear(session_factory)
    assert (await api.get("/api/v1/auth/status", headers=tenant.admin)).json() == {
        "has_users": False
    }
    body = {"email": " Boss@Example.COM ", "name": "Boss", "password": PW}
    first = await api.post("/api/v1/auth/bootstrap", json=body, headers=tenant.admin)
    assert first.status_code == 201, first.text
    user = first.json()
    assert user["email"] == "boss@example.com" and user["role"] == "admin"
    assert set(user) == {"id", "email", "name", "role", "disabled", "created_at", "last_login_at"}
    second = await api.post("/api/v1/auth/bootstrap", json=body, headers=tenant.admin)
    assert second.status_code == 409 and second.json()["error"]["code"] == "already_bootstrapped"
    assert (await api.get("/api/v1/auth/status", headers=tenant.admin)).json() == {
        "has_users": True
    }
    assert (await api.get("/api/v1/auth/status", headers=tenant.read)).status_code == 403


async def test_login_ok_wrong_unknown_disabled(api: AsyncClient, tenant: Tenant) -> None:
    user = await _admin(api, tenant, "login@example.com")
    ok = await api.post(
        "/api/v1/auth/login",
        json={"email": "LOGIN@example.com", "password": PW},
        headers=tenant.admin,
    )
    assert ok.status_code == 200 and ok.json()["last_login_at"] is not None
    wrong = await api.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "nope nope nope"},
        headers=tenant.admin,
    )
    unknown = await api.post(
        "/api/v1/auth/login",
        json={"email": "who@example.com", "password": PW},
        headers=tenant.admin,
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "invalid_credentials"

    await _admin(api, tenant, "other-admin@example.com")  # so disabling is allowed
    patched = await api.patch(
        f"/api/v1/users/{user['id']}", json={"disabled": True}, headers=tenant.admin
    )
    assert patched.status_code == 200 and patched.json()["disabled"] is True
    disabled = await api.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": PW},
        headers=tenant.admin,
    )
    assert disabled.status_code == 403 and disabled.json()["error"]["code"] == "account_disabled"
    bad_pw = await api.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "nope nope nope"},
        headers=tenant.admin,
    )
    assert bad_pw.status_code == 401  # disabled is only revealed after a correct password


async def test_duplicate_email_and_password_policy(api: AsyncClient, tenant: Tenant) -> None:
    await _admin(api, tenant, "dup@example.com")
    dup = await api.post(
        "/api/v1/users",
        json={"email": "DUP@example.com", "name": "B", "password": PW, "role": "member"},
        headers=tenant.admin,
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "email_taken"
    for pw in ("short", "x" * 201):
        bad = await api.post(
            "/api/v1/users",
            json={"email": "pw@example.com", "name": "B", "password": pw, "role": "member"},
            headers=tenant.admin,
        )
        assert bad.status_code == 422, bad.text
    invalid = await api.post(
        "/api/v1/users",
        json={"email": "not-an-email", "name": "B", "password": PW, "role": "member"},
        headers=tenant.admin,
    )
    assert invalid.status_code == 400


async def test_last_admin_protected_and_hash_never_returned(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _clear(session_factory)
    only = await _admin(api, tenant, "only@example.com")
    url = f"/api/v1/users/{only['id']}"
    for change in ({"disabled": True}, {"role": "member"}):
        r = await api.patch(url, json=change, headers=tenant.admin)
        assert r.status_code == 409 and r.json()["error"]["code"] == "last_admin"
    ok = await api.patch(
        url, json={"name": "Renamed", "password": "another long password"}, headers=tenant.admin
    )
    assert ok.status_code == 200 and ok.json()["name"] == "Renamed"
    second = await _admin(api, tenant, "second@example.com")
    demote = await api.patch(url, json={"role": "member"}, headers=tenant.admin)
    assert demote.status_code == 200 and demote.json()["role"] == "member"
    assert (
        await api.patch(
            f"/api/v1/users/{second['id']}", json={"disabled": True}, headers=tenant.admin
        )
    ).status_code == 409
    missing = await api.patch(
        "/api/v1/users/00000000-0000-0000-0000-000000000000",
        json={"name": "x"},
        headers=tenant.admin,
    )
    assert missing.status_code == 404

    listing = await api.get("/api/v1/users", headers=tenant.admin)
    assert [u["email"] for u in listing.json()["items"]] == [
        "only@example.com",
        "second@example.com",
    ]
    for text in (listing.text, ok.text, demote.text):
        assert "scrypt" not in text and "password" not in text
