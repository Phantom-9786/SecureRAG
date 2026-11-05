"""Real PostgreSQL/storage/API tests; embeddings are explicitly mocked, never sent externally."""

from uuid import UUID, uuid4

from sqlalchemy import delete, event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Chunk, Document, RolePermission
from app.rag.embeddings import EmbeddingBusy, EmbeddingError, get_embedder
from app.services.storage import PDFStorage, get_storage
from tests.helpers import ORIGIN, create_user, headers, login, role_map
from tests.pdf_helpers import make_pdf


class FakeEmbeddings:
    """Test-only vectors exercise persistence, not semantic quality or real provider access."""

    def __init__(self):
        self.calls = []
        self.error = None
        self.configured = True
        self.dimensions = 1536
        self.on_embed = None

    def ensure_configured(self):
        if not self.configured:
            raise EmbeddingError("No test key")

    def embed_documents(self, texts, deadline):
        self.calls.append(texts)
        if self.on_embed:
            self.on_embed()
        if self.error:
            raise self.error
        return [[1.0] + [0.0] * (self.dimensions - 1) for _ in texts]


def configure_documents(client, tmp_path):
    fake = FakeEmbeddings()
    storage = PDFStorage(tmp_path / "private", 1024 * 1024)
    client.app.dependency_overrides[get_storage] = lambda: storage
    client.app.dependency_overrides[get_embedder] = lambda: fake
    return fake, storage


def upload(client, profile, category, payload=None, filename="policy.pdf", extra_headers=None):
    return client.post(
        "/api/v1/admin/documents",
        headers=extra_headers or headers(profile),
        data={"title": "Company policy", "category_id": category},
        files={
            "file": (
                filename,
                payload
                if payload is not None
                else make_pdf(
                    [
                        "Policy on page one",
                        "Policy on page two",
                    ]
                ),
                "application/pdf",
            )
        },
    )


def assert_failed(connection, document_id):
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        document = db.get(Document, UUID(document_id))
        assert document.ingestion_status == "failed" and document.active is False
        assert (
            db.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(
                    Chunk.document_id == document.id,
                )
            )
            == 0
        )


def test_document_lifecycle_and_authorized_file_access(api, tmp_path):
    (admin, engineer, anonymous), connection = api
    fake, storage = configure_documents(admin, tmp_path)
    profile = login(admin)
    roles = role_map(admin)
    account = create_user(admin, profile, roles["Engineer"]["id"])
    engineer_profile = login(engineer, account["email"])
    general = next(c["id"] for c in profile["categories"] if c["name"] == "General")
    hr = next(c["id"] for c in profile["categories"] if c["name"] == "HR")
    assert upload(anonymous, profile, general).status_code == 401
    assert upload(engineer, engineer_profile, general).status_code == 403
    assert upload(admin, profile, general, extra_headers=ORIGIN).status_code == 403
    assert fake.calls == [] and not storage.root.exists()
    payload = make_pdf(["General handbook page one", "General handbook page two"])
    response = upload(admin, profile, general, payload=payload)
    assert response.status_code == 201, response.text
    general_doc = response.json()
    assert general_doc["active"] is True and general_doc["ingestion_status"] == "ready"
    assert "storage_key" not in general_doc and "embedding" not in general_doc
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        chunks = list(
            db.scalars(
                select(Chunk)
                .where(Chunk.document_id == UUID(general_doc["id"]))
                .order_by(Chunk.chunk_index)
            )
        )
        assert [chunk.page_number for chunk in chunks] == [1, 2]
        assert [chunk.chunk_index for chunk in chunks] == [0, 1]
        assert all(len(chunk.embedding) == 1536 for chunk in chunks)
        document = db.get(Document, UUID(general_doc["id"]))
        assert storage.path_for(document.storage_key).read_bytes() == payload
    hr_response = upload(admin, profile, hr)
    assert hr_response.status_code == 201
    hr_id = hr_response.json()["id"]
    assert {d["id"] for d in engineer.get("/api/v1/documents").json()} == {general_doc["id"]}
    assert engineer.get("/api/v1/admin/documents").status_code == 403
    assert len(admin.get("/api/v1/admin/documents?limit=1").json()) == 1
    missing = engineer.get(f"/api/v1/documents/{uuid4()}")
    denied = engineer.get(f"/api/v1/documents/{hr_id}")
    assert missing.status_code == denied.status_code == 404 and missing.json() == denied.json()
    assert engineer.get(f"/api/v1/documents/{hr_id}/file").status_code == 404
    download = engineer.get(f"/api/v1/documents/{general_doc['id']}/file")
    assert download.status_code == 200 and download.content == payload
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["cache-control"] == "no-store"
    for active in (False, True):
        result = admin.patch(
            f"/api/v1/admin/documents/{general_doc['id']}",
            headers=headers(profile),
            json={"active": active},
        )
        assert result.status_code == 200
        assert engineer.get(f"/api/v1/documents/{general_doc['id']}/file").status_code == (
            200 if active else 404
        )
    assert (
        admin.put(
            f"/api/v1/roles/{roles['Engineer']['id']}/grants",
            headers=headers(profile),
            json={"category_ids": [], "permission_ids": []},
        ).status_code
        == 200
    )
    assert engineer.get(f"/api/v1/documents/{general_doc['id']}/file").status_code == 404


def test_failed_ingestion_never_publishes_partial_chunks(api, tmp_path):
    (admin, _, _), connection = api
    fake, storage = configure_documents(admin, tmp_path)
    profile = login(admin)
    general = profile["categories"][0]["id"]
    fake.configured = False
    assert upload(admin, profile, general).status_code == 503
    assert not storage.root.exists()
    fake.configured = True
    assert upload(admin, profile, general, payload=b"not-a-pdf").status_code == 415
    failed_ids = []
    for payload in (b"%PDF-invalid", make_pdf([None]), make_pdf(["Private"], password="secret")):
        response = upload(admin, profile, general, payload=payload)
        assert response.status_code == 422, response.text
        document_id = response.json()["detail"]["document_id"]
        failed_ids.append(document_id)
        assert_failed(connection, document_id)
    assert fake.calls == []
    fake.error = EmbeddingError("Gemini embedding service is unavailable")
    response = upload(admin, profile, general)
    assert response.status_code == 502
    assert_failed(connection, response.json()["detail"]["document_id"])
    fake.error = None
    fake.dimensions = 768
    response = upload(admin, profile, general)
    assert response.status_code == 502
    assert_failed(connection, response.json()["detail"]["document_id"])
    fake.dimensions = 1536

    def fail_after_insert(mapper, connection, target):
        if target.chunk_index == 1:
            raise SQLAlchemyError("private SQL parameters must not be echoed")

    event.listen(Chunk, "after_insert", fail_after_insert)
    try:
        response = upload(admin, profile, general)
    finally:
        event.remove(Chunk, "after_insert", fail_after_insert)
    assert response.status_code == 503
    assert "private SQL" not in response.text
    all_documents = admin.get("/api/v1/admin/documents").json()
    assert len(all_documents) == 6
    for document in all_documents:
        assert_failed(connection, document["id"])
    assert admin.get("/api/v1/documents").json() == []
    assert (
        admin.patch(
            f"/api/v1/admin/documents/{failed_ids[0]}",
            headers=headers(profile),
            json={"active": True},
        ).status_code
        == 409
    )


def test_revoked_uploader_cannot_publish(api, tmp_path):
    (admin, uploader, _), connection = api
    fake, _ = configure_documents(admin, tmp_path)
    profile = login(admin)
    roles = role_map(admin)
    account = create_user(admin, profile, roles["Engineer"]["id"])
    permission = next(
        p for p in admin.get("/api/v1/permissions").json() if p["code"] == "documents.manage"
    )
    assert (
        admin.put(
            f"/api/v1/roles/{roles['Engineer']['id']}/grants",
            headers=headers(profile),
            json={
                "category_ids": roles["Engineer"]["category_ids"],
                "permission_ids": [permission["id"]],
            },
        ).status_code
        == 200
    )
    uploader_profile = login(uploader, account["email"])

    def revoke_permission():
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            db.execute(
                delete(RolePermission).where(
                    RolePermission.role_id == UUID(roles["Engineer"]["id"]),
                    RolePermission.permission_id == UUID(permission["id"]),
                )
            )
            db.commit()

    fake.on_embed = revoke_permission
    response = upload(uploader, uploader_profile, uploader_profile["categories"][0]["id"])
    assert response.status_code == 403
    documents = admin.get("/api/v1/admin/documents").json()
    assert len(documents) == 1
    assert_failed(connection, documents[0]["id"])


def test_rate_limited_ingestion_returns_retry_after_and_stays_inactive(api, tmp_path):
    (admin, _, _), connection = api
    fake, _ = configure_documents(admin, tmp_path)
    fake.error = EmbeddingBusy(120)
    profile = login(admin)
    response = upload(admin, profile, profile["categories"][0]["id"])
    assert response.status_code == 429
    assert response.headers["retry-after"] == "120"
    assert_failed(connection, response.json()["detail"]["document_id"])


def test_upload_request_and_file_limits(api, tmp_path, monkeypatch):
    (admin, _, _), _connection = api
    fake, storage = configure_documents(admin, tmp_path)
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    profile = login(admin)
    category = profile["categories"][0]["id"]
    # File limit inside the small multipart-overhead allowance; partial private file is removed.
    oversize = b"%PDF-" + b"a" * (1024 * 1024)
    assert upload(admin, profile, category, payload=oversize).status_code == 413
    # Header-based total request limit.
    oversize += b"a" * (32 * 1024)
    assert upload(admin, profile, category, payload=oversize).status_code == 413
    # Same limit without Content-Length, exercising the actual received-byte counter.
    boundary = "securerag-test-boundary"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nPolicy\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="category_id"\r\n\r\n{category}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="policy.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode()
        + oversize
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request_headers = {
        **headers(profile),
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    response = admin.post(
        "/api/v1/admin/documents",
        headers=request_headers,
        content=(body[i : i + 65536] for i in range(0, len(body), 65536)),
    )
    assert response.status_code == 413, response.text
    assert upload(admin, profile, str(uuid4())).status_code == 404
    assert fake.calls == []
    assert admin.get("/api/v1/admin/documents").json() == []
    assert not storage.root.exists() or not list(storage.root.iterdir())
