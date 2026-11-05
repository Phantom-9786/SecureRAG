"""Real Gemini embedding integration; test doubles are supplied only by test overrides."""

import math
import time
from collections.abc import Sequence

from google.genai import types

from app.core.config import Settings, get_settings
from app.services.gemini import (
    GeminiBusy,
    GeminiError,
    GeminiPool,
    estimate_input_tokens,
    get_gemini_pool,
)


class EmbeddingError(RuntimeError):
    pass


class EmbeddingBusy(EmbeddingError):
    def __init__(self, retry_after: int):
        super().__init__("Gemini capacity is temporarily unavailable; retry later")
        self.retry_after = retry_after


def validate_vectors(
    vectors: Sequence[Sequence[float]], expected_count: int, dimensions: int = 1536
) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise EmbeddingError("Embedding provider returned an invalid response")
    result = []
    for vector in vectors:
        if len(vector) != dimensions or any(not math.isfinite(value) for value in vector):
            raise EmbeddingError("Embedding provider returned an invalid vector")
        norm = math.sqrt(sum(value * value for value in vector))
        if not math.isfinite(norm) or norm == 0:
            raise EmbeddingError("Embedding provider returned an invalid vector")
        # Reduced Gemini 001 embeddings need normalization; query vectors must use the same rule.
        result.append([value / norm for value in vector])
    return result


class GeminiEmbeddings:
    def __init__(self, settings: Settings, pool: GeminiPool | None = None):
        self.settings = settings
        self.pool = pool if pool is not None else GeminiPool(settings)

    def ensure_configured(self) -> None:
        try:
            self.pool.ensure_configured()
        except GeminiError:
            raise EmbeddingError("GEMINI_API_KEY is not configured") from None

    def embed_query(self, question: str, deadline: float) -> list[float]:
        self.ensure_configured()

        def operation(client, timeout_ms):
            return client.models.embed_content(
                model=self.settings.embedding_model,
                contents=[question],
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=self.settings.embedding_dimensions,
                    http_options=types.HttpOptions(timeout=timeout_ms),
                ),
            )

        try:
            response = self.pool.call(
                self.settings.embedding_model, [question], deadline, operation
            )
            vectors = [embedding.values or [] for embedding in response.embeddings or []]
            return validate_vectors(vectors, 1, self.settings.embedding_dimensions)[0]
        except GeminiBusy as error:
            raise EmbeddingBusy(error.retry_after) from None
        except GeminiError as error:
            raise EmbeddingError(str(error)) from None

    def embed_documents(self, texts: list[str], deadline: float) -> list[list[float]]:
        self.ensure_configured()
        result = []
        try:
            position = 0
            maximum = self.pool.max_request_tokens(self.settings.embedding_model)
            while position < len(texts):
                batch = []
                while position < len(texts) and len(batch) < 32:
                    if estimate_input_tokens([*batch, texts[position]]) > maximum:
                        break
                    batch.append(texts[position])
                    position += 1
                if not batch:
                    raise EmbeddingError("Chunk exceeds the configured embedding token budget")
                if deadline <= time.monotonic():
                    raise EmbeddingError("Embedding generation timed out")

                def operation(client, timeout_ms, batch=batch):
                    return client.models.embed_content(
                        model=self.settings.embedding_model,
                        contents=batch,
                        config=types.EmbedContentConfig(
                            task_type="RETRIEVAL_DOCUMENT",
                            output_dimensionality=self.settings.embedding_dimensions,
                            http_options=types.HttpOptions(timeout=timeout_ms),
                        ),
                    )

                response = self.pool.call(self.settings.embedding_model, batch, deadline, operation)
                vectors = [embedding.values or [] for embedding in response.embeddings or []]
                result.extend(
                    validate_vectors(vectors, len(batch), self.settings.embedding_dimensions)
                )
        except EmbeddingError:
            raise
        except GeminiBusy as error:
            raise EmbeddingBusy(error.retry_after) from None
        except GeminiError as error:
            raise EmbeddingError(str(error)) from None
        return result


def get_embedder() -> GeminiEmbeddings:
    return GeminiEmbeddings(get_settings(), get_gemini_pool())
