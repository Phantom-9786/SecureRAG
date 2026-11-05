ORIGIN = {"Origin": "http://localhost:3000"}
PASSWORD = "integration-password-only-482!"


def login(client, email="admin@example.com", password=PASSWORD):
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}, headers=ORIGIN
    )
    assert response.status_code == 200, response.text
    return response.json()


def headers(profile):
    return {**ORIGIN, "X-CSRF-Token": profile["csrf_token"]}


def role_map(client):
    response = client.get("/api/v1/roles")
    assert response.status_code == 200
    return {role["name"]: role for role in response.json()}


def create_user(client, profile, role_id, email="engineer@example.com"):
    response = client.post(
        "/api/v1/users",
        headers=headers(profile),
        json={
            "name": "Test Engineer",
            "email": email,
            "password": PASSWORD,
            "role_id": role_id,
        },
    )
    assert response.status_code == 201, response.text
    assert "password" not in response.text and "token_version" not in response.text
    return response.json()
