"""Real PostgreSQL RAG security tests; provider requests are explicitly mocked."""

import json
import math
from uuid import UUID, uuid4

import httpx
from google import genai
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    Category,
    Chunk,
    Document,
    Message,
    MessageSource,
    RoleCategoryAccess,
    User,
)
from app.rag.citations import NO_EVIDENCE, WITHHELD_ANSWER
from app.rag.embeddings import EmbeddingError, get_embedder
from app.rag.generation import GeneratedAnswer, get_generator
from app.services.gemini import GeminiBusy, GeminiPool
from tests.helpers import ORIGIN, create_user, headers, login, role_map


class QueryEmbedder:
    def __init__(self):
        self.vector = [1.0] + [0.0] * 1535
        self.calls = []
        self.error = None
        self.callback = None

    def embed_query(self, question, deadline):
        self.calls.append(question)
        if self.callback:
            self.callback()
        if self.error:
            raise self.error
        return self.vector


class RecordingGenerator:
    def __init__(self):
        self.calls = []
        self.text = "Authorized engineering answer [S1]"
        self.error = None
        self.callback = None

    def __call__(self, question, context, documents, mode):
        self.calls.append(
            {"question": question, "context": context, "documents": documents, "mode": mode}
        )
        if self.callback:
            self.callback()
        if self.error:
            raise self.error
        return GeneratedAnswer(self.text, "test-model", "Test generation")


def setup_user(api):
    (admin, engineer, other), connection = api
    profile = login(admin)
    roles = role_map(admin)
    account = create_user(admin, profile, roles["Engineer"]["id"])
    engineer_profile = login(engineer, account["email"])
    embedder, generator = QueryEmbedder(), RecordingGenerator()
    admin.app.dependency_overrides[get_embedder] = lambda: embedder
    admin.app.dependency_overrides[get_generator] = lambda: generator
    return admin, engineer, other, connection, profile, engineer_profile, roles, embedder, generator


def seed_documents(connection):
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        admin_id = db.scalar(select(User.id).where(User.email == "admin@example.com"))
        categories = {c.name: c.id for c in db.scalars(select(Category))}
        result = {}
        for name, category, similarity, active, status in (
            ("General", "General", 0.8, True, "ready"),
            ("Engineering", "Engineering", 0.9, True, "ready"),
            ("HR", "HR", 1.0, True, "ready"),
            ("Finance", "Finance", 1.0, True, "ready"),
            ("Management", "Management", 1.0, True, "ready"),
            ("Inactive", "General", 1.0, False, "ready"),
            ("Failed", "General", 1.0, True, "failed"),
            ("Unrelated", "General", 0.0, True, "ready"),
        ):
            doc = Document(
                id=uuid4(),
                title=name + "_DOCUMENT_CANARY",
                original_filename=name + ".pdf",
                storage_key=uuid4().hex + ".pdf",
                category_id=categories[category],
                uploaded_by=admin_id,
                active=active,
                ingestion_status=status,
            )
            db.add(doc)
            db.flush()
            chunk = Chunk(
                id=uuid4(),
                document_id=doc.id,
                chunk_index=0,
                page_number=3,
                content=name.upper() + "_CONTENT_CANARY policy text.",
                embedding=[similarity, math.sqrt(1 - similarity**2)] + [0.0] * 1534,
            )
            db.add(chunk)
            result[name] = {
                "document_id": str(doc.id),
                "chunk_id": str(chunk.id),
                "category_id": str(categories[category]),
            }
        db.commit()
    return result


def new_conversation(client, profile):
    response = client.post("/api/v1/conversations", headers=headers(profile), json={})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def ask(client, profile, conversation, question="What are the engineering rules?", **extra):
    return client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers=headers(profile),
        json={"question": question, "model_mode": "basic", **extra},
    )


def test_permissions_precede_vector_rank_and_actual_sdk_context(api, monkeypatch):
    admin, engineer, other, connection, profile, ep, roles, _embedder, _ = setup_user(api)
    docs = seed_documents(connection)
    monkeypatch.setenv("RAG_TOP_K", "2")
    get_settings.cache_clear()
    settings = Settings(
        _env_file=None, gemini_api_key="mock-key-only", gemini_basic_model="test-basic"
    )
    pool = GeminiPool(settings)
    monkeypatch.setattr("app.rag.generation.get_settings", lambda: settings)
    monkeypatch.setattr("app.rag.generation.get_gemini_pool", lambda: pool)
    real_client = genai.Client
    outgoing = []

    def handler(request):
        outgoing.append(request.content.decode())
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "Engineering policy answer [S1]"}],
                        },
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    def factory(**kwargs):
        kwargs["http_options"].client_args = {"transport": httpx.MockTransport(handler)}
        return real_client(**kwargs)

    monkeypatch.setattr("app.services.gemini.genai.Client", factory)
    admin.app.dependency_overrides.pop(get_generator)
    conversation = new_conversation(engineer, ep)
    response = ask(engineer, ep, conversation)
    assert response.status_code == 201, response.text
    assert len(outgoing) == 1
    body = outgoing[0]
    assert "ENGINEERING_CONTENT_CANARY" in body and "GENERAL_CONTENT_CANARY" in body
    for denied in ("HR", "FINANCE", "MANAGEMENT", "INACTIVE", "FAILED", "UNRELATED"):
        assert denied + "_CONTENT_CANARY" not in body
    sources = response.json()["answer"]["sources"]
    assert len(sources) == 1 and sources[0]["document_id"] == docs["Engineering"]["document_id"]
    assert sources[0]["page_number"] == 3
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        answer_id = UUID(response.json()["answer"]["id"])
        assert (
            db.scalar(
                select(func.count())
                .select_from(MessageSource)
                .where(MessageSource.message_id == answer_id)
            )
            == 2
        )
    history = engineer.get(f"/api/v1/conversations/{conversation}/messages")
    assert history.status_code == 200 and [m["role"] for m in history.json()] == [
        "user",
        "assistant",
    ]
    assert "Engineering policy answer" in history.json()[1]["content"]
    assert admin.get(f"/api/v1/conversations/{conversation}").status_code == 404
    assert admin.get(f"/api/v1/conversations/{conversation}/messages").status_code == 404
    assert ask(admin, profile, conversation).status_code == 404
    assert other.get("/api/v1/conversations").status_code == 401
    assert (
        engineer.post(
            f"/api/v1/conversations/{conversation}/messages",
            headers=ORIGIN,
            json={"question": "No CSRF"},
        ).status_code
        == 403
    )
    assert ask(engineer, ep, conversation, role_id=roles["Admin"]["id"]).status_code == 422
    assert len(outgoing) == 1


def test_history_hides_answer_when_any_used_source_is_revoked(api):
    admin, engineer, _, connection, profile, ep, roles, _, generator = setup_user(api)
    docs = seed_documents(connection)
    conversation = new_conversation(engineer, ep)
    result = ask(engineer, ep, conversation)
    assert result.status_code == 201
    assert (
        result.json()["answer"]["sources"][0]["document_id"] == docs["Engineering"]["document_id"]
    )
    # Only S1 is cited, but removing S2's category must still withhold the entire stored answer.
    engineering_category = docs["Engineering"]["category_id"]
    response = admin.put(
        f"/api/v1/roles/{roles['Engineer']['id']}/grants",
        headers=headers(profile),
        json={"category_ids": [engineering_category], "permission_ids": []},
    )
    assert response.status_code == 200
    history = engineer.get(f"/api/v1/conversations/{conversation}/messages").json()
    assert (
        history[1]["withheld"]
        and history[1]["content"] == WITHHELD_ANSWER
        and history[1]["sources"] == []
    )
    assert "Authorized engineering answer" not in json.dumps(history)
    assert (
        admin.put(
            f"/api/v1/roles/{roles['Engineer']['id']}/grants",
            headers=headers(profile),
            json={"category_ids": roles["Engineer"]["category_ids"], "permission_ids": []},
        ).status_code
        == 200
    )
    assert not engineer.get(f"/api/v1/conversations/{conversation}/messages").json()[1]["withheld"]
    assert (
        admin.patch(
            "/api/v1/admin/documents/" + docs["General"]["document_id"],
            headers=headers(profile),
            json={"active": False},
        ).status_code
        == 200
    )
    assert engineer.get(f"/api/v1/conversations/{conversation}/messages").json()[1]["withheld"]
    assert len(generator.calls) == 1


def test_insufficient_evidence_provider_errors_and_atomic_message_writes(api):
    _admin, engineer, _, connection, _profile, ep, _roles, embedder, generator = setup_user(api)
    conversation = new_conversation(engineer, ep)
    response = ask(engineer, ep, conversation)
    assert response.status_code == 201 and response.json()["answer"]["content"] == NO_EVIDENCE
    assert response.json()["model"] == "none" and response.json()["answer"]["sources"] == []
    assert not embedder.calls and not generator.calls
    seed_documents(connection)
    embedder.vector = [0.0, 0.0, 1.0] + [0.0] * 1533
    response = ask(engineer, ep, conversation)
    assert response.status_code == 201 and response.json()["answer"]["content"] == NO_EVIDENCE
    assert not generator.calls  # Below-threshold authorized evidence does not go to the LLM.
    embedder.vector = [1.0] + [0.0] * 1535
    baseline = engineer.get(f"/api/v1/conversations/{conversation}/messages").json()
    generator.error = GeminiBusy(120)
    response = ask(engineer, ep, conversation)
    assert response.status_code == 429 and response.headers["retry-after"] == "120"
    generator.error = None
    embedder.error = EmbeddingError("Sanitized provider failure")
    assert ask(engineer, ep, conversation).status_code == 503
    embedder.error = None
    generator.text = "Hallucinated answer [S999]"
    assert ask(engineer, ep, conversation).status_code == 502
    generator.text = "Authorized answer [S1]"

    def fail_sources(mapper, conn, source):
        raise SQLAlchemyError("private SQL data must not escape")

    event.listen(MessageSource, "after_insert", fail_sources)
    try:
        response = ask(engineer, ep, conversation)
        assert response.status_code == 503 and "private SQL" not in response.text
    finally:
        event.remove(MessageSource, "after_insert", fail_sources)
    assert engineer.get(f"/api/v1/conversations/{conversation}/messages").json() == baseline


def test_fresh_authorization_after_embedding_and_after_generation(api):
    admin, engineer, _, connection, profile, ep, roles, embedder, generator = setup_user(api)
    docs = seed_documents(connection)
    conversation = new_conversation(engineer, ep)

    def remove_engineering():
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            db.execute(
                delete(RoleCategoryAccess).where(
                    RoleCategoryAccess.role_id == UUID(roles["Engineer"]["id"]),
                    RoleCategoryAccess.category_id == UUID(docs["Engineering"]["category_id"]),
                )
            )
            db.commit()

    embedder.callback = remove_engineering
    response = ask(engineer, ep, conversation)
    assert response.status_code == 201
    assert "ENGINEERING_CONTENT_CANARY" not in generator.calls[-1]["context"]
    assert "GENERAL_CONTENT_CANARY" in generator.calls[-1]["context"]
    embedder.callback = None
    assert (
        admin.put(
            f"/api/v1/roles/{roles['Engineer']['id']}/grants",
            headers=headers(profile),
            json={"category_ids": roles["Engineer"]["category_ids"], "permission_ids": []},
        ).status_code
        == 200
    )
    baseline = engineer.get(f"/api/v1/conversations/{conversation}/messages").json()
    generator.callback = remove_engineering
    response = ask(engineer, ep, conversation)
    assert response.status_code == 409
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        assert db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == UUID(conversation))
        ) == len(baseline)

    def deactivate_during_generation():
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            db.execute(
                update(User)
                .where(User.id == UUID(ep["user"]["id"]))
                .values(
                    is_active=False,
                    token_version=User.token_version + 1,
                )
            )
            db.commit()

    generator.callback = deactivate_during_generation
    assert ask(engineer, ep, conversation).status_code == 401
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        assert db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == UUID(conversation),
            )
        ) == len(baseline)


def test_same_conversation_conflict_keeps_one_complete_turn(api):
    _admin, engineer, _, connection, _profile, ep, _roles, _, generator = setup_user(api)
    seed_documents(connection)
    conversation = new_conversation(engineer, ep)
    inner_results = []
    triggered = False

    def concurrent_turn():
        nonlocal triggered
        if not triggered:
            triggered = True
            inner_results.append(ask(engineer, ep, conversation, question="The other request wins"))

    generator.callback = concurrent_turn
    outer = ask(engineer, ep, conversation, question="First request still generating")
    assert inner_results[0].status_code == 201
    assert outer.status_code == 409
    history = engineer.get(f"/api/v1/conversations/{conversation}/messages").json()
    assert len(history) == 2 and history[0]["content"] == "The other request wins"
    assert [m["role"] for m in history] == ["user", "assistant"]
