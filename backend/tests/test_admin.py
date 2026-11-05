from fastapi.testclient import TestClient

from app.main import create_app


def test_admin_lookups_and_google_provisioning_require_authentication():
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/admin/options").status_code == 401
        assert client.post("/api/v1/users/google", json={}).status_code == 401
