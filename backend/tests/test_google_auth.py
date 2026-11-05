import json
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.auth.exceptions import TransportError

from app.core.config import Settings, get_settings
from app.main import create_app
from app.services.google_auth import validate_claims, verify_google_credential

CLIENT_ID = "unit-test.apps.googleusercontent.com"
NONCE = "n" * 43


def claims(**overrides):
    now = int(time.time())
    return {
        "sub": "google-subject-1",
        "email": "person@gmail.com",
        "email_verified": True,
        "nonce": NONCE,
        "aud": CLIENT_ID,
        "iss": "https://accounts.google.com",
        "iat": now,
        "exp": now + 300,
        **overrides,
    }


@pytest.fixture(scope="module")
def signing_keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


def verifier_transport(monkeypatch, public):
    def request(url, **kwargs):
        assert url == "https://www.googleapis.com/oauth2/v1/certs"
        assert kwargs["timeout"] == 10
        return SimpleNamespace(status=200, data=json.dumps({"test-key": public}).encode())

    monkeypatch.setattr("app.services.google_auth.Request", lambda: request)


def test_real_google_auth_library_verifies_rsa_token(monkeypatch, signing_keys):
    private, public = signing_keys
    verifier_transport(monkeypatch, public)
    token = jwt.encode(claims(), private, algorithm="RS256", headers={"kid": "test-key"})
    identity = verify_google_credential(token, CLIENT_ID)
    assert identity.subject == "google-subject-1"
    assert identity.authoritative_email
    assert identity.nonce == NONCE


@pytest.mark.parametrize(
    "override",
    [
        {"aud": "other-client.apps.googleusercontent.com"},
        {"iss": "https://evil.example"},
        {"exp": 1},
        {"iat": int(time.time()) + 3600},
        {"email_verified": False},
        {"nonce": ""},
        {"sub": ""},
    ],
)
def test_forged_or_invalid_identity_claims_rejected(monkeypatch, signing_keys, override):
    private, public = signing_keys
    verifier_transport(monkeypatch, public)
    token = jwt.encode(claims(**override), private, algorithm="RS256", headers={"kid": "test-key"})
    with pytest.raises(HTTPException) as error:
        verify_google_credential(token, CLIENT_ID)
    assert error.value.status_code == 401
    assert token not in error.value.detail


def test_bad_signature_rejected(monkeypatch, signing_keys):
    _, public = signing_keys
    verifier_transport(monkeypatch, public)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(claims(), key, algorithm="RS256", headers={"kid": "test-key"})
    with pytest.raises(HTTPException) as error:
        verify_google_credential(token, CLIENT_ID)
    assert error.value.status_code == 401


def test_google_transport_failure_is_sanitized(monkeypatch):
    def request(*args, **kwargs):
        raise TransportError("provider-secret-diagnostic")

    monkeypatch.setattr("app.services.google_auth.Request", lambda: request)
    with pytest.raises(HTTPException) as error:
        verify_google_credential("credential-secret", CLIENT_ID)
    assert error.value.status_code == 503
    assert "secret" not in error.value.detail


@pytest.mark.parametrize(
    "email,hd,authoritative",
    [
        ("person@gmail.com", None, True),
        ("person@company.com", "company.com", True),
        ("person@third-party.com", None, False),
        ("person@third-party.com", "", False),
    ],
)
def test_email_authority_does_not_trust_email_verified_alone(email, hd, authoritative):
    identity = validate_claims(claims(email=email, hd=hd))
    assert identity.authoritative_email is authoritative


def test_google_disabled_and_origin_checks(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/api/v1/auth/google/config").json() == {
                "enabled": False,
                "client_id": None,
            }
            assert client.post("/api/v1/auth/google/challenge").status_code == 403
            assert (
                client.post("/api/v1/auth/google", json={"credential": "token"}).status_code == 403
            )
            assert (
                client.post(
                    "/api/v1/auth/google/challenge", headers={"Origin": "http://localhost:3000"}
                ).status_code
                == 503
            )
    finally:
        get_settings.cache_clear()


def test_google_client_id_is_not_a_gemini_key():
    assert Settings(_env_file=None, google_client_id="").google_client_id is None
    assert Settings(_env_file=None, google_client_id=CLIENT_ID).google_client_id == CLIENT_ID
    with pytest.raises(ValueError):
        Settings(_env_file=None, google_client_id="not-an-oauth-client")
