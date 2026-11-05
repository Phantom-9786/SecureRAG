from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models import Permission, Role, RolePermission, User
from tests.helpers import ORIGIN, PASSWORD, create_user, headers, login, role_map


def test_admin_options_and_google_user_creation(api):
    (admin, employee, _), connection = api
    profile = login(admin)
    roles = role_map(admin)
    options = admin.get("/api/v1/admin/options")
    assert options.status_code == 200
    assert len(options.json()["roles"]) == 6
    assert len(options.json()["categories"]) == 5
    assert len(options.json()["permissions"]) == 3
    assert options.json()["max_upload_mb"] >= 1
    body = {
        "name": "Google Employee",
        "email": "new.google.user@gmail.com",
        "role_id": roles["Employee"]["id"],
    }
    assert admin.post("/api/v1/users/google", headers=ORIGIN, json=body).status_code == 403
    assert (
        admin.post(
            "/api/v1/users/google",
            headers={**headers(profile), "Origin": "https://evil.example"},
            json=body,
        ).status_code
        == 403
    )
    created = admin.post("/api/v1/users/google", headers=headers(profile), json=body)
    assert created.status_code == 201
    assert created.json()["is_active"] is True
    assert "password" not in created.text and "google_subject" not in created.text
    assert (
        admin.post("/api/v1/users/google", headers=headers(profile), json=body).status_code == 409
    )
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        user = db.scalar(select(User).where(User.email == body["email"]))
        assert user.google_subject is None
        assert not verify_password(user.password_hash, PASSWORD)
    account = create_user(admin, profile, roles["Employee"]["id"])
    login(employee, account["email"])
    assert employee.get("/api/v1/admin/options").status_code == 403
    assert (
        employee.post(
            "/api/v1/users/google", headers=headers(login(employee, account["email"])), json=body
        ).status_code
        == 403
    )


def test_admin_options_respect_each_independent_management_grant(api):
    (admin, manager, _), connection = api
    profile = login(admin)
    for index, code in enumerate(("users.manage", "roles.manage", "documents.manage")):
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            role = Role(name=f"Only {code}")
            db.add(role)
            db.flush()
            permission_id = db.scalar(select(Permission.id).where(Permission.code == code))
            db.add(RolePermission(role_id=role.id, permission_id=permission_id))
            db.add(
                User(
                    name=f"Manager {index}",
                    email=f"manager{index}@example.com",
                    role_id=role.id,
                    password_hash=hash_password(PASSWORD),
                )
            )
            db.commit()
        login(manager, f"manager{index}@example.com")
        result = manager.get("/api/v1/admin/options")
        assert result.status_code == 200
        data = result.json()
        assert bool(data["roles"]) is (code == "users.manage")
        assert bool(data["categories"]) is (code in {"roles.manage", "documents.manage"})
        assert bool(data["permissions"]) is (code == "roles.manage")
        assert (manager.get("/api/v1/users").status_code == 200) is (code == "users.manage")
        assert (manager.get("/api/v1/roles").status_code == 200) is (code == "roles.manage")
        assert (manager.get("/api/v1/admin/documents").status_code == 200) is (
            code == "documents.manage"
        )
        assert (
            manager.get("/api/v1/categories").json() == []
        )  # Management does not imply document-read access.
    assert admin.get("/api/v1/auth/me").json()["permissions"] == profile["permissions"]
