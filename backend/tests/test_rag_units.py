from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.rag.citations import NO_EVIDENCE, GroundingError, build_context, referenced_sources
from app.rag.embeddings import GeminiEmbeddings
from app.rag.retrieval import RetrievedChunk, retrieval_statement
from app.schemas.conversations import QuestionInput
from tests.test_document_processing import mock_google_transport


def chunk(content="Allowed source text", page=1):
    return RetrievedChunk(
        uuid4(), uuid4(), "Authorized document", "allowed.pdf", page, content, 0.9
    )


def test_retrieval_materializes_database_permissions_before_distance():
    statement = retrieval_statement(uuid4(), 0, [1.0] + [0.0] * 1535, 5, 0.6)
    sql = str(statement.compile(dialect=postgresql.dialect()))
    before_ranking = sql[: sql.index("<=>")]
    assert "AS MATERIALIZED" in before_ranking
    assert "JOIN role_category_access" in before_ranking
    assert "JOIN users" in before_ranking
    assert "users.token_version" in before_ranking
    assert "documents.active IS true" in before_ranking
    assert "documents.ingestion_status" in before_ranking
    assert "ORDER BY" in sql and "LIMIT" in sql


def test_context_is_bounded_unicode_safe_and_resolves_real_metadata():
    oversized = chunk("x" * 7000)
    allowed = chunk("कंपनी की अधिकृत नीति।", page=7)
    context, sources = build_context([oversized, allowed], max_bytes=1000)
    assert len(context.encode("utf-8")) <= 1000
    assert len(sources) == 1 and sources[0].number == 1
    assert "\ufffd" not in context
    citation = sources[0].citation()
    assert citation.chunk_id == allowed.chunk_id and citation.page_number == 7
    assert str(allowed.document_id) in citation.download_url
    assert "x" * 100 not in context


@pytest.mark.parametrize(
    "answer",
    [
        "Uncited invented answer",
        "Unknown [S9]",
        "Bad [S0]",
        "Bad [S01]",
        "Bad combined [S1, S2]",
        "Mixed valid and forged [S1] [S1000]",
        "",
    ],
)
def test_unknown_or_missing_citations_fail_closed(answer):
    with pytest.raises(GroundingError):
        referenced_sources(answer, {1, 2})


def test_valid_citations_are_deduplicated_and_abstention_needs_none():
    assert referenced_sources("First [S2], then [S1], repeated [S2].", {1, 2}) == [2, 1]
    assert referenced_sources(NO_EVIDENCE, set()) == []


@pytest.mark.parametrize(
    "body",
    [
        {"question": " "},
        {"question": "nul\x00text"},
        {"question": "x" * 2001},
        {"question": "क" * 900},
        {"question": "Hello", "role_id": str(uuid4())},
        {"question": "Hello", "model_mode": "unrestricted"},
    ],
)
def test_question_validation_bounds_input_and_rejects_privilege_fields(body):
    with pytest.raises(ValidationError):
        QuestionInput(**body)


def test_query_embedding_uses_query_task_and_same_dimensions(monkeypatch):
    import json
    import time

    def handler(request):
        body = json.loads(request.content)
        assert len(body["requests"]) == 1
        assert body["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
        assert body["requests"][0]["outputDimensionality"] == 1536
        return httpx.Response(200, json={"embeddings": [{"values": [3, 4] + [0] * 1534}]})

    mock_google_transport(monkeypatch, handler)
    embedder = GeminiEmbeddings(Settings(_env_file=None, gemini_api_key="test-key-only"))
    vector = embedder.embed_query("Question?", time.monotonic() + 10)
    assert len(vector) == 1536 and vector[:2] == [0.6, 0.8]
