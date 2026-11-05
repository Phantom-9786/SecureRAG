"""Real PostgreSQL authentication/RBAC integration tests."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.bootstrap_admin import bootstrap_admin
from app.models import Role, User
from tests.helpers import ORIGIN, PASSWORD, create_user, headers, login, role_map


def test_login_csrf_logout_and_replay(api):
    (admin, employee, replay), _ = api
    for email in ("missing@example.com", "admin@example.com"):
        bad = admin.post(
            "/api/v1/auth/login",
            headers=ORIGIN,
            json={"email": email, "password": "wrong-password"},
        )
        assert bad.status_code == 401
        assert bad.json()["detail"] == "Invalid email or password"
    profile = login(admin, email=" ADMIN@EXAMPLE.COM ")
    assert set(profile["permissions"]) == {"users.manage", "roles.manage", "documents.manage"}
    assert len(profile["categories"]) == 5
    roles = role_map(admin)
    body = {
        "name": "Blocked",
        "email": "blocked@example.com",
        "password": PASSWORD,
        "role_id": roles["Engineer"]["id"],
    }
    assert admin.post("/api/v1/users", json=body, headers=ORIGIN).status_code == 403
    bad_origin = {**headers(profile), "Origin": "https://evil.example"}
    assert admin.post("/api/v1/users", json=body, headers=bad_origin).status_code == 403
    fake = {**ORIGIN, "X-CSRF-Token": "forged-token"}
    admin.cookies.set("securerag_csrf", "forged-token", domain="testserver.local", path="/")
    assert admin.post("/api/v1/users", json=body, headers=fake).status_code == 403
    profile = login(admin)
    account = create_user(admin, profile, roles["Engineer"]["id"])
    duplicate = admin.post(
        "/api/v1/users",
        headers=headers(profile),
        json={
            **body,
            "email": account["email"],
        },
    )
    assert duplicate.status_code == 409
    engineer_profile = login(employee, account["email"])
    assert engineer_profile["permissions"] == []
    assert {c["name"] for c in employee.get("/api/v1/categories").json()} == {
        "General",
        "Engineering",
    }
    assert employee.get("/api/v1/users").status_code == 403
    assert employee.get("/api/v1/roles").status_code == 403
    assert (
        employee.post("/api/v1/users", headers=headers(engineer_profile), json=body).status_code
        == 403
    )
    old_token = employee.cookies.get("securerag_access")
    replay.cookies.set("securerag_access", old_token)
    assert (
        employee.post("/api/v1/auth/logout", headers=headers(engineer_profile)).status_code == 204
    )
    assert employee.cookies.get("securerag_access") is None
    assert replay.get("/api/v1/auth/me").status_code == 401
    assert employee.get("/api/v1/auth/me").status_code == 401


def test_current_roles_deactivation_and_grants(api):
    (admin, employee, _), _ = api
    profile = login(admin)
    roles = role_map(admin)
    account = create_user(admin, profile, roles["Engineer"]["id"])
    login(employee, account["email"])
    assert (
        admin.patch(
            f"/api/v1/users/{account['id']}",
            headers=headers(profile),
            json={"role_id": roles["HR"]["id"]},
        ).status_code
        == 200
    )
    me = employee.get("/api/v1/auth/me").json()
    assert me["role"]["name"] == "HR"
    assert {c["name"] for c in me["categories"]} == {"General", "HR"}
    general_id = next(c["id"] for c in profile["categories"] if c["name"] == "General")
    assert (
        admin.put(
            f"/api/v1/roles/{roles['HR']['id']}/grants",
            headers=headers(profile),
            json={"category_ids": [general_id], "permission_ids": []},
        ).status_code
        == 200
    )
    assert {c["name"] for c in employee.get("/api/v1/categories").json()} == {"General"}
    # Invalid grants leave the previously committed policy intact.
    assert (
        admin.put(
            f"/api/v1/roles/{roles['HR']['id']}/grants",
            headers=headers(profile),
            json={"category_ids": [str(uuid4())], "permission_ids": []},
        ).status_code
        == 422
    )
    assert {c["name"] for c in employee.get("/api/v1/categories").json()} == {"General"}
    assert (
        admin.patch(
            f"/api/v1/users/{account['id']}", headers=headers(profile), json={"is_active": False}
        ).status_code
        == 200
    )
    assert employee.get("/api/v1/auth/me").status_code == 401
    denied = employee.post(
        "/api/v1/auth/login", headers=ORIGIN, json={"email": account["email"], "password": PASSWORD}
    )
    assert denied.status_code == 401
    assert (
        admin.patch(
            f"/api/v1/users/{account['id']}", headers=headers(profile), json={"is_active": True}
        ).status_code
        == 200
    )
    assert (
        employee.get("/api/v1/auth/me").status_code == 401
    )  # Reactivation never revives old cookies.
    login(employee, account["email"])


def test_last_admin_and_bootstrap_are_protected(api):
    (admin, second, _), connection = api
    profile = login(admin)
    roles = role_map(admin)
    my_id = profile["user"]["id"]
    assert (
        admin.patch(
            f"/api/v1/users/{my_id}", headers=headers(profile), json={"is_active": False}
        ).status_code
        == 409
    )
    assert (
        admin.patch(
            f"/api/v1/users/{my_id}",
            headers=headers(profile),
            json={"role_id": roles["Employee"]["id"]},
        ).status_code
        == 409
    )
    assert (
        admin.put(
            f"/api/v1/roles/{roles['Admin']['id']}/grants",
            headers=headers(profile),
            json={"category_ids": [], "permission_ids": []},
        ).status_code
        == 409
    )
    assert len(admin.get("/api/v1/auth/me").json()["permissions"]) == 3
    account = create_user(admin, profile, roles["Admin"]["id"], "second@example.com")
    second_profile = login(second, account["email"])
    assert (
        second.patch(
            f"/api/v1/users/{my_id}",
            headers=headers(second_profile),
            json={"role_id": roles["Employee"]["id"]},
        ).status_code
        == 200
    )
    assert (
        admin.get("/api/v1/users").status_code == 403
    )  # Current DB role, despite old signed cookie.
    assert (
        second.patch(
            f"/api/v1/users/{account['id']}",
            headers=headers(second_profile),
            json={"is_active": False},
        ).status_code
        == 409
    )
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        with pytest.raises(ValueError, match="first user"):
            bootstrap_admin(db, "Blocked", "blocked@example.com", PASSWORD)
        assert db.scalar(select(User).where(User.email == "blocked@example.com")) is None
        # Permission checks never depend on a role's display name.
        role = db.scalar(select(Role).where(Role.name == "Admin"))
        role.name = "Renamed administrator"
        db.commit()
    assert second.get("/api/v1/users").status_code == 200
