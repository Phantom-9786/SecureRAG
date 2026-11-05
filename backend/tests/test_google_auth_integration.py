from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import GoogleLoginChallenge, User
from app.services.google_auth import GoogleIdentity, digest
from tests.helpers import ORIGIN, create_user, headers, login, role_map

CLIENT_ID = "integration.apps.googleusercontent.com"


def configure(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    get_settings.cache_clear()


def prepare(client):
    response = client.post("/api/v1/auth/google/challenge", headers=ORIGIN)
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    return response.json()["nonce"]


def mock_google(
    monkeypatch, nonce, subject="subject-1", email="person@gmail.com", authoritative=True
):
    monkeypatch.setattr(
        "app.services.google_auth.verify_google_credential",
        lambda credential, client_id: GoogleIdentity(subject, email, authoritative, nonce),
    )


def submit(client):
    return client.post(
        "/api/v1/auth/google", headers=ORIGIN, json={"credential": "mock-google-token"}
    )


def test_google_login_binding_current_grants_and_replay(api, monkeypatch):
    (admin, employee, replay), connection = api
    configure(monkeypatch)
    admin_profile = login(admin)
    roles = role_map(admin)
    account = create_user(admin, admin_profile, roles["Engineer"]["id"], email="person@gmail.com")
    nonce = prepare(employee)
    old_cookie = employee.cookies.get("securerag_google")
    mock_google(monkeypatch, nonce)
    result = submit(employee)
    assert result.status_code == 200
    assert result.json()["user"]["id"] == account["id"]
    assert result.json()["role"]["name"] == "Engineer"
    assert {c["name"] for c in result.json()["categories"]} == {"General", "Engineering"}
    assert result.json()["permissions"] == []
    assert employee.cookies.get("securerag_access")
    assert employee.cookies.get("securerag_google") is None
    replay.cookies.set("securerag_google", old_cookie)
    assert submit(replay).status_code == 401
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        user = db.scalar(select(User).where(User.email == "person@gmail.com"))
        assert user.google_subject == "subject-1"
    # Bound subject wins even if the verified Google email changes; local grants stay current.
    admin.patch(
        f"/api/v1/users/{account['id']}",
        headers=headers(admin_profile),
        json={"role_id": roles["HR"]["id"]},
    )
    nonce = prepare(employee)
    mock_google(monkeypatch, nonce, email="renamed@gmail.com")
    result = submit(employee)
    assert result.status_code == 200
    assert result.json()["role"]["name"] == "HR"
    assert employee.post("/api/v1/auth/logout", headers=headers(result.json())).status_code == 204
    assert employee.get("/api/v1/auth/me").status_code == 401


def test_google_denies_unprovisioned_inactive_and_non_authoritative(api, monkeypatch):
    (admin, employee, _), _ = api
    configure(monkeypatch)
    admin_profile = login(admin)
    roles = role_map(admin)
    account = create_user(
        admin, admin_profile, roles["Employee"]["id"], email="person@third-party.com"
    )
    nonce = prepare(employee)
    mock_google(monkeypatch, nonce, email=account["email"], authoritative=False)
    assert submit(employee).status_code == 403
    nonce = prepare(employee)
    mock_google(monkeypatch, nonce, email="unknown@gmail.com")
    assert submit(employee).status_code == 403
    assert len(admin.get("/api/v1/users").json()) == 2  # No silent signup.
    inactive = create_user(
        admin, admin_profile, roles["Employee"]["id"], email="inactive@gmail.com"
    )
    admin.patch(
        f"/api/v1/users/{inactive['id']}", headers=headers(admin_profile), json={"is_active": False}
    )
    nonce = prepare(employee)
    mock_google(monkeypatch, nonce, email=inactive["email"])
    assert submit(employee).status_code == 403
    assert employee.cookies.get("securerag_access") is None


def test_google_challenge_binding_expiry_and_conflicting_subject(api, monkeypatch):
    (admin, employee, other), connection = api
    configure(monkeypatch)
    admin_profile = login(admin)
    roles = role_map(admin)
    create_user(admin, admin_profile, roles["Employee"]["id"], email="person@gmail.com")
    nonce = prepare(employee)
    mock_google(monkeypatch, nonce)
    assert submit(other).status_code == 401  # No initiating browser cookie.
    mock_google(monkeypatch, "wrong-nonce" * 4)
    assert submit(employee).status_code == 401
    mock_google(monkeypatch, nonce)
    cookie = employee.cookies.get("securerag_google")
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        challenge = db.get(GoogleLoginChallenge, digest(cookie))
        challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert submit(employee).status_code == 401
    nonce = prepare(employee)
    mock_google(monkeypatch, nonce)
    assert submit(employee).status_code == 200
    nonce = prepare(other)
    mock_google(monkeypatch, nonce, subject="different-google-account")
    assert submit(other).status_code == 403  # Same email cannot replace an existing binding.
