import io
import math
import re
import time

import httpx
import pytest
from fastapi import HTTPException
from google import genai

from app.core.config import Settings
from app.rag.chunking import CHUNK_BYTES, chunk_pages
from app.rag.embeddings import EmbeddingError, GeminiEmbeddings, validate_vectors
from app.rag.extraction import PageText, PDFProcessingError, clean_text, extract_pages
from app.services.storage import PDFStorage
from tests.pdf_helpers import make_pdf


def test_private_storage_never_uses_upload_paths(tmp_path):
    storage = PDFStorage(tmp_path / "private", max_bytes=1024)
    key, name = storage.save(io.BytesIO(b"%PDF-test"), "../../handbook.pdf", "application/pdf")
    assert name == "handbook.pdf"
    assert storage.path_for(key).parent == storage.root
    assert storage.path_for(key).read_bytes() == b"%PDF-test"
    for invalid in ("../secret.pdf", "C:/secret.pdf", "not-a-key.pdf"):
        with pytest.raises(ValueError):
            storage.path_for(invalid)


def test_storage_rejects_wrong_types_and_cleans_partial_uploads(tmp_path):
    storage = PDFStorage(tmp_path, max_bytes=10)
    for data, name, mime, status in (
        (b"not-pdf", "file.pdf", "application/pdf", 415),
        (b"%PDF-hello", "file.txt", "application/pdf", 415),
        (b"%PDF-hello", "file.pdf", "text/html", 415),
        (b"%PDF-hello", "file\r\n.pdf", "application/pdf", 415),
        (b"%PDF-" + b"a" * 100, "file.pdf", "application/pdf", 413),
    ):
        with pytest.raises(HTTPException) as error:
            storage.save(io.BytesIO(data), name, mime)
        assert error.value.status_code == status
    assert not list(tmp_path.iterdir())


def test_storage_collision_cannot_remove_an_existing_pdf(tmp_path, monkeypatch):
    from uuid import UUID

    identifier = UUID("11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr("app.services.storage.uuid4", lambda: identifier)
    storage = PDFStorage(tmp_path, max_bytes=1024)
    original = storage.path_for(identifier.hex + ".pdf")
    original.write_bytes(b"existing-private-pdf")
    with pytest.raises(FileExistsError):
        storage.save(io.BytesIO(b"%PDF-new"), "new.pdf", "application/pdf")
    assert original.read_bytes() == b"existing-private-pdf"


def test_extraction_preserves_original_page_numbers(tmp_path):
    path = tmp_path / "test.pdf"
    path.write_bytes(make_pdf(["Page one policy", None, "Page three policy"]))
    pages = extract_pages(path, Settings(_env_file=None))
    assert [(page.page_number, page.text) for page in pages] == [
        (1, "Page one policy"),
        (3, "Page three policy"),
    ]
    assert clean_text("  A\t B\x00\r\n\r\n\r\n C ") == "A B\n\nC"


@pytest.mark.parametrize(
    "payload,match",
    [
        (b"%PDF-invalid", "valid text-based"),
        (make_pdf([None]), "No extractable text"),
        (make_pdf(["Private"], password="secret"), "Encrypted"),
    ],
)
def test_invalid_scanned_and_encrypted_pdfs_are_rejected(tmp_path, payload, match):
    path = tmp_path / "bad.pdf"
    path.write_bytes(payload)
    with pytest.raises(PDFProcessingError, match=match):
        extract_pages(path, Settings(_env_file=None))


def test_pdf_resource_limits(tmp_path):
    path = tmp_path / "limit.pdf"
    path.write_bytes(make_pdf(["First page", "Second page"]))
    with pytest.raises(PDFProcessingError, match="page limit"):
        extract_pages(path, Settings(_env_file=None, max_pdf_pages=1))
    path.write_bytes(make_pdf(["x" * 1500]))
    with pytest.raises(PDFProcessingError, match="text exceeds"):
        extract_pages(path, Settings(_env_file=None, max_document_characters=1000))
    with pytest.raises(PDFProcessingError, match="page content"):
        extract_pages(path, Settings(_env_file=None, max_page_stream_bytes=1024))


def test_chunks_cover_text_preserve_pages_and_unicode():
    english = "\n\n".join(
        " ".join(f"word{index}" for index in range(start, start + 100))
        for start in range(0, 900, 100)
    )
    hindi = "कंपनी की इंजीनियरिंग नीति सभी कर्मचारियों के लिए उपलब्ध है। " * 100
    chunks = chunk_pages([PageText(1, english), PageText(4, hindi)], max_chunks=100)
    assert len(chunks) > 2
    assert all(len(chunk.content.encode("utf-8")) <= CHUNK_BYTES for chunk in chunks)
    assert all("\ufffd" not in chunk.content for chunk in chunks)
    words = set(re.findall(r"word\d+", " ".join(c.content for c in chunks if c.page_number == 1)))
    assert words == set(re.findall(r"word\d+", english))
    assert {chunk.page_number for chunk in chunks} == {1, 4}
    assert len("".join(c.content for c in chunks)) > len(english) + len(hindi)  # overlap exists
    with pytest.raises(PDFProcessingError, match="maximum number"):
        chunk_pages([PageText(1, english)], max_chunks=1)


@pytest.mark.parametrize(
    "vector", [[0.0] * 1536, [1.0] * 768, [float("nan")] * 1536, [float("inf")] * 1536]
)
def test_invalid_embeddings_are_rejected(vector):
    with pytest.raises(EmbeddingError):
        validate_vectors([vector], 1)
    with pytest.raises(EmbeddingError):
        validate_vectors([], 1)


def mock_google_transport(monkeypatch, handler):
    real_client = genai.Client
    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs):
        kwargs["http_options"].client_args = {"transport": transport}
        return real_client(**kwargs)

    monkeypatch.setattr("app.services.gemini.genai.Client", client_factory)


def test_gemini_sdk_batch_request_and_vector_normalization(monkeypatch):
    import json

    batch_sizes = []

    def respond(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path.endswith("gemini-embedding-001:batchEmbedContents")
        body = json.loads(request.content)
        requests = body["requests"]
        batch_sizes.append(len(requests))
        assert all(item["taskType"] == "RETRIEVAL_DOCUMENT" for item in requests)
        assert all(item["outputDimensionality"] == 1536 for item in requests)
        return httpx.Response(
            200, json={"embeddings": [{"values": [3.0, 4.0] + [0.0] * 1534} for _ in requests]}
        )

    mock_google_transport(monkeypatch, respond)
    embedder = GeminiEmbeddings(Settings(_env_file=None, gemini_api_key="unit-test-only"))
    vectors = embedder.embed_documents(
        [f"Policy {index}" for index in range(35)], time.monotonic() + 30
    )
    assert batch_sizes == [32, 3]
    assert len(vectors) == 35
    assert vectors[0][:2] == [0.6, 0.8]
    assert math.isclose(sum(value * value for value in vectors[0]), 1)


def test_provider_errors_are_sanitized_and_not_retried(monkeypatch):
    calls = []

    def unavailable(request):
        calls.append(request)
        return httpx.Response(
            429,
            json={
                "error": {
                    "code": 429,
                    "message": "private-document-and-secret-key",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )

    mock_google_transport(monkeypatch, unavailable)
    embedder = GeminiEmbeddings(Settings(_env_file=None, gemini_api_key="unit-test-only"))
    with pytest.raises(EmbeddingError) as error:
        embedder.embed_documents(["Policy"], time.monotonic() + 30)
    assert len(calls) == 1
    assert "private-document" not in str(error.value)


def test_missing_key_fails_closed():
    with pytest.raises(EmbeddingError, match="not configured"):
        GeminiEmbeddings(Settings(_env_file=None, gemini_api_key=None)).ensure_configured()
