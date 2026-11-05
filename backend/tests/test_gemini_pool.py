import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.core.config import Settings
from app.rag.generation import generate_answer
from app.rag.model_routing import choose_model_tier
from app.services.gemini import GeminiBusy, GeminiPool


def settings(**overrides):
    return Settings(
        _env_file=None,
        **{
            "gemini_api_key": "test-key-1",
            "gemini_api_key_2": "test-key-2",
            "gemini_api_key_3": "test-key-3",
            "gemini_project_id": "project-1",
            "gemini_project_id_2": "project-2",
            "gemini_project_id_3": "project-3",
            "gemini_max_wait_seconds": 0,
            **overrides,
        },
    )


def test_concurrent_first_requests_share_one_pool(monkeypatch):
    import app.services.gemini as module

    pool = GeminiPool(settings())
    calls = []
    barrier = threading.Barrier(8)

    def factory(configuration):
        calls.append(1)
        time.sleep(0.01)  # Force an overlapping initialization window.
        return pool

    monkeypatch.setattr(module, "_pool", None)
    monkeypatch.setattr(module, "GeminiPool", factory)

    def get(index):
        barrier.wait(timeout=2)
        return module.get_gemini_pool()

    with ThreadPoolExecutor(max_workers=8) as executor:
        instances = list(executor.map(get, range(8)))
    assert calls == [1]
    assert all(instance is pool for instance in instances)


def test_all_keys_are_active_peers():
    pool = GeminiPool(settings())
    chosen = []
    for _ in range(6):
        reservation = pool.acquire("model", 10, time.monotonic() + 10)
        chosen.append(reservation.credential.name)
        pool.release(reservation)
    assert chosen == ["key-1", "key-2", "key-3"] * 2


def test_parallel_requests_use_three_keys_without_duplicate_calls(monkeypatch):
    real_client = genai.Client
    barrier = threading.Barrier(3)
    seen = []
    lock = threading.Lock()

    def handler(request):
        with lock:
            seen.append(request.headers["x-goog-api-key"])
        barrier.wait(timeout=5)  # Would fail if the pool serialized the three independent requests.
        return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0]}]})

    def factory(**kwargs):
        kwargs["http_options"].client_args = {"transport": httpx.MockTransport(handler)}
        return real_client(**kwargs)

    monkeypatch.setattr("app.services.gemini.genai.Client", factory)
    pool = GeminiPool(settings())

    def request(index):
        return pool.call(
            "gemini-embedding-001",
            [f"independent question {index}"],
            time.monotonic() + 10,
            lambda client, timeout: client.models.embed_content(
                model="gemini-embedding-001",
                contents=[f"question {index}"],
                config=types.EmbedContentConfig(output_dimensionality=2),
            ),
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        responses = list(executor.map(request, range(3)))
    assert len(responses) == 3
    assert sorted(seen) == ["test-key-1", "test-key-2", "test-key-3"]
    assert all(key.inflight == 0 for key in pool.credentials)


def test_same_project_keys_share_rate_budget():
    pool = GeminiPool(
        settings(
            gemini_project_id="same",
            gemini_project_id_2="same",
            gemini_project_id_3="same",
            gemini_default_rpm=1,
        )
    )
    first = pool.acquire("model", 10, time.monotonic() + 10)
    pool.release(first)
    with pytest.raises(GeminiBusy):
        pool.acquire("model", 10, time.monotonic() + 10)
    other_model = pool.acquire("different-model", 10, time.monotonic() + 10)
    pool.release(other_model)


def test_input_token_and_daily_budgets_are_enforced():
    pool = GeminiPool(
        settings(
            gemini_api_key_2=None,
            gemini_api_key_3=None,
            gemini_default_tpm=100,
            gemini_default_rpd=2,
        )
    )
    first = pool.acquire("model", 80, time.monotonic() + 10)
    pool.release(first)
    with pytest.raises(GeminiBusy):
        pool.acquire("model", 21, time.monotonic() + 10)
    second = pool.acquire("model", 20, time.monotonic() + 10)
    pool.release(second)
    # A cleared minute window must not remove the independent daily cap.
    first.budget.minute.clear()
    with pytest.raises(GeminiBusy):
        pool.acquire("model", 1, time.monotonic() + 10)
    first.budget.day = "1900-01-01"
    next_day = pool.acquire("model", 1, time.monotonic() + 10)
    pool.release(next_day)


def test_provider_429_cools_entire_project_not_sibling_key():
    pool = GeminiPool(settings(gemini_project_id="same", gemini_project_id_2="same"))
    first = pool.acquire("model", 10, time.monotonic() + 10)
    error = errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "private provider body",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "120s"}
                ],
            }
        },
    )
    pool.on_error(first, "model", error)
    pool.release(first)
    second = pool.acquire("model", 10, time.monotonic() + 10)
    assert second.credential.project == "project-3"
    assert first.budget.cooldown_until >= time.monotonic() + 119
    pool.release(second)


def test_provider_daily_exhaustion_is_not_retried_each_minute():
    pool = GeminiPool(settings())
    reservation = pool.acquire("model", 10, time.monotonic() + 10)
    error = errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "quota",
                "details": [{"violations": [{"quotaId": "RequestsPerDayPerProjectPerModel"}]}],
            }
        },
    )
    pool.on_error(reservation, "model", error)
    assert reservation.budget.daily_requests == reservation.budget.rpd
    pool.release(reservation)


def test_per_model_project_overrides_and_maximum_concurrency():
    pool = GeminiPool(
        settings(
            gemini_max_parallel_requests=1,
            gemini_rate_limits=[
                {
                    "project_id": "project-1",
                    "model": "model",
                    "rpm": 1,
                    "tpm": 500,
                    "rpd": 3,
                }
            ],
        )
    )
    first = pool.acquire("model", 20, time.monotonic() + 10)
    assert first.budget.rpm == 1
    with pytest.raises(GeminiBusy):
        pool.acquire("model", 20, time.monotonic() + 10)
    pool.release(first)
    second = pool.acquire("model", 20, time.monotonic() + 10)
    assert second.credential.project == "project-2"
    pool.release(second)


def test_credential_configuration_rejects_duplicates_and_redacts_secrets():
    with pytest.raises(ValidationError):
        settings(gemini_api_key_2="test-key-1")
    assert "test-key-1" not in repr(GeminiPool(settings()).credentials)


@pytest.mark.parametrize(
    "status,details",
    [
        (400, [{"reason": "API_KEY_INVALID"}]),
        (429, [{"retryDelay": "60s"}]),
        (503, []),
    ],
)
def test_failed_key_request_can_use_another_eligible_peer(monkeypatch, status, details):
    seen = []
    real_client = genai.Client

    def handler(request):
        key = request.headers["x-goog-api-key"]
        seen.append(key)
        if key == "test-key-1":
            return httpx.Response(
                status,
                json={
                    "error": {
                        "code": status,
                        "message": "private text and key",
                        "details": details,
                    }
                },
            )
        return httpx.Response(200, json={"embeddings": [{"values": [1.0]}]})

    def factory(**kwargs):
        kwargs["http_options"].client_args = {"transport": httpx.MockTransport(handler)}
        return real_client(**kwargs)

    monkeypatch.setattr("app.services.gemini.genai.Client", factory)
    pool = GeminiPool(settings())
    result = pool.call(
        "gemini-embedding-001",
        ["document"],
        time.monotonic() + 10,
        lambda client, timeout: client.models.embed_content(
            model="gemini-embedding-001", contents=["document"]
        ),
    )
    assert len(result.embeddings) == 1
    assert seen == ["test-key-1", "test-key-2"]
    assert all(key.inflight == 0 for key in pool.credentials)


def test_waiting_request_resumes_when_capacity_is_released():
    pool = GeminiPool(
        settings(gemini_api_key_2=None, gemini_api_key_3=None, gemini_max_wait_seconds=2)
    )
    first = pool.acquire("model", 1, time.monotonic() + 10)
    started = threading.Event()

    def waiter():
        started.set()
        return pool.acquire("model", 1, time.monotonic() + 5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(waiter)
        assert started.wait(timeout=1)
        assert not future.done()
        pool.release(first)
        second = future.result(timeout=2)
        pool.release(second)


@pytest.mark.parametrize(
    "question,chars,documents,tier",
    [
        ("How many annual leave days are allowed?", 500, 1, "basic"),
        ("Compare HR and Engineering onboarding policies", 500, 2, "advanced"),
        ("Summarize the findings", 13000, 1, "advanced"),
        ("What applies to my situation?", 500, 3, "advanced"),
        ("First? Second? Third?", 500, 1, "advanced"),
    ],
)
def test_explainable_model_routing(question, chars, documents, tier):
    assert choose_model_tier(question, chars, documents).tier == tier
    assert choose_model_tier(question, chars, documents, "advanced").tier == "advanced"


def test_no_evidence_never_calls_gemini(monkeypatch):
    def forbidden():
        raise AssertionError("Should not create a provider request")

    monkeypatch.setattr("app.rag.generation.get_gemini_pool", forbidden)
    result = generate_answer("Private information?", "", 0)
    assert result.model == "none"


def test_generation_uses_selected_model_with_grounding_instruction(monkeypatch):
    configuration = settings(
        gemini_basic_model="configured-basic-model",
        gemini_advanced_model="configured-advanced-model",
        gemini_advanced_thinking_level="low",
        gemini_generation_timeout_seconds=45,
    )
    selected = []
    real_client = genai.Client

    def handler(request):
        import json

        body = json.loads(request.content)
        selected.append(request.url.path)
        assert "supplied authorized sources" in str(body["systemInstruction"])
        assert 44 <= float(request.extensions["timeout"]["read"]) <= 45
        if request.url.path.endswith("configured-advanced-model:generateContent"):
            thinking = body["generationConfig"]["thinkingConfig"]
            level = thinking.get("thinkingLevel", thinking.get("thinking_level"))
            assert level.lower() == "low"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "Grounded answer [S1]"}]},
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    def factory(**kwargs):
        kwargs["http_options"].client_args = {"transport": httpx.MockTransport(handler)}
        return real_client(**kwargs)

    monkeypatch.setattr("app.services.gemini.genai.Client", factory)
    monkeypatch.setattr("app.rag.generation.get_settings", lambda: configuration)
    monkeypatch.setattr("app.rag.generation.get_gemini_pool", lambda: GeminiPool(configuration))
    simple = generate_answer("How many days?", "[S1] Five days.", 1)
    advanced = generate_answer("Compare the policies", "[S1] Five days. [S2] Seven days.", 2)
    assert simple.model == "configured-basic-model"
    assert advanced.model == "configured-advanced-model"
    assert selected[0].endswith("configured-basic-model:generateContent")
    assert selected[1].endswith("configured-advanced-model:generateContent")
    assert advanced.text == "Grounded answer [S1]"
