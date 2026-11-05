"""A shared, thread-safe Gemini key pool for one V1 API worker process.

Keys are peers. Quotas are reserved atomically by project/model before every request;
different requests can use different keys concurrently, without duplicating a prompt.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import TypeVar
from zoneinfo import ZoneInfo

import httpx
from google import genai
from google.genai import errors, types
from pydantic import SecretStr

from app.core.config import Settings, get_settings

T = TypeVar("T")
PACIFIC = ZoneInfo("America/Los_Angeles")


def error_details(error: errors.APIError) -> list[dict]:
    details = getattr(error, "details", None)
    if isinstance(details, dict):
        if isinstance(details.get("error"), dict):
            details = details["error"]
        details = details.get("details", [])
    return [item for item in details if isinstance(item, dict)] if isinstance(details, list) else []


def invalid_api_key(error: errors.APIError) -> bool:
    return any(item.get("reason") == "API_KEY_INVALID" for item in error_details(error))


class GeminiError(RuntimeError):
    """Only safe, application-authored messages may cross this boundary."""


class GeminiBusy(GeminiError):
    def __init__(self, retry_after: int = 60):
        super().__init__("Gemini capacity is temporarily unavailable; retry later")
        self.retry_after = max(1, retry_after)


@dataclass
class Credential:
    name: str
    project: str
    secret: SecretStr = field(repr=False)
    inflight: int = 0
    disabled: bool = False
    blocked_models: set[str] = field(default_factory=set)
    cooldown_until: float = 0


@dataclass
class Budget:
    rpm: int
    tpm: int
    rpd: int
    minute: deque[tuple[float, int]] = field(default_factory=deque)
    day: str = ""
    daily_requests: int = 0
    cooldown_until: float = 0

    def refresh(self, now: float) -> None:
        while self.minute and self.minute[0][0] <= now - 60:
            self.minute.popleft()
        day = datetime.now(PACIFIC).date().isoformat()
        if day != self.day:
            self.day = day
            self.daily_requests = 0

    def permits(self, tokens: int, now: float) -> bool:
        self.refresh(now)
        return (
            now >= self.cooldown_until
            and self.daily_requests < self.rpd
            and len(self.minute) < self.rpm
            and sum(count for _, count in self.minute) + tokens <= self.tpm
        )


@dataclass
class Reservation:
    credential: Credential
    budget: Budget


def estimate_input_tokens(texts: list[str]) -> int:
    # UTF-8 bytes are a deliberately conservative estimate, not the Gemini tokenizer.
    return max(1, sum(len(text.encode("utf-8")) for text in texts) + 64 * len(texts))


class GeminiPool:
    def __init__(self, settings: Settings):
        self.settings = settings
        slots = (
            ("key-1", settings.gemini_project_id, settings.gemini_api_key),
            ("key-2", settings.gemini_project_id_2, settings.gemini_api_key_2),
            ("key-3", settings.gemini_project_id_3, settings.gemini_api_key_3),
        )
        self.credentials = [
            Credential(name, project, secret)
            for name, project, secret in slots
            if secret is not None
        ]
        self.condition = threading.Condition()
        self.budgets: dict[tuple[str, str], Budget] = {}
        self.cursor = 0

    def ensure_configured(self) -> None:
        if not self.credentials:
            raise GeminiError("GEMINI_API_KEY is not configured")

    def budget_for(self, project: str, model: str) -> Budget:
        scope = (project, model)
        if scope not in self.budgets:
            configured = next(
                (
                    limit
                    for limit in self.settings.gemini_rate_limits
                    if (limit.project_id, limit.model) == scope
                ),
                None,
            )
            self.budgets[scope] = Budget(
                rpm=configured.rpm if configured else self.settings.gemini_default_rpm,
                tpm=configured.tpm if configured else self.settings.gemini_default_tpm,
                rpd=configured.rpd if configured else self.settings.gemini_default_rpd,
            )
        return self.budgets[scope]

    def max_request_tokens(self, model: str) -> int:
        self.ensure_configured()
        with self.condition:
            return max(self.budget_for(key.project, model).tpm for key in self.credentials)

    def retry_after(self, model: str, tokens: int = 1) -> int:
        with self.condition:
            now = time.monotonic()
            waits = []
            for key in self.credentials:
                if key.disabled or model in key.blocked_models:
                    continue
                budget = self.budget_for(key.project, model)
                budget.refresh(now)
                wait = max(1, key.cooldown_until - now, budget.cooldown_until - now)
                if budget.minute and (
                    len(budget.minute) >= budget.rpm
                    or sum(count for _, count in budget.minute) + tokens > budget.tpm
                ):
                    wait = max(wait, budget.minute[-1][0] + 60 - now)
                if budget.daily_requests >= budget.rpd:
                    wall = datetime.now(PACIFIC)
                    reset = (wall + timedelta(days=1)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    wait = max(wait, reset.timestamp() - wall.timestamp())
                waits.append(wait)
            return max(1, math.ceil(min(waits))) if waits else 60

    def acquire(
        self, model: str, tokens: int, deadline: float, excluded: set[str] | None = None
    ) -> Reservation:
        self.ensure_configured()
        excluded = excluded or set()
        wait_until = min(deadline, time.monotonic() + self.settings.gemini_max_wait_seconds)
        with self.condition:
            while True:
                now = time.monotonic()
                if now >= deadline:
                    raise GeminiBusy(self.retry_after(model, tokens))
                if not any(
                    not key.disabled and model not in key.blocked_models for key in self.credentials
                ):
                    raise GeminiError("No configured credential can access this Gemini model")
                maximum = max(
                    self.budget_for(key.project, model).tpm
                    for key in self.credentials
                    if not key.disabled and model not in key.blocked_models
                )
                if tokens > maximum:
                    raise GeminiError("Request exceeds the configured Gemini input token budget")
                inflight = sum(key.inflight for key in self.credentials)
                for offset in range(len(self.credentials)):
                    index = (self.cursor + offset) % len(self.credentials)
                    key = self.credentials[index]
                    if (
                        key.name in excluded
                        or key.disabled
                        or model in key.blocked_models
                        or key.inflight
                        or key.cooldown_until > now
                        or inflight >= self.settings.gemini_max_parallel_requests
                    ):
                        continue
                    budget = self.budget_for(key.project, model)
                    if not budget.permits(tokens, now):
                        continue
                    budget.minute.append((now, tokens))
                    budget.daily_requests += 1
                    key.inflight += 1
                    self.cursor = (index + 1) % len(self.credentials)
                    return Reservation(key, budget)
                if now >= wait_until:
                    raise GeminiBusy(self.retry_after(model, tokens))
                self.condition.wait(timeout=min(0.25, wait_until - now))

    def release(self, reservation: Reservation) -> None:
        with self.condition:
            reservation.credential.inflight -= 1
            self.condition.notify_all()

    def on_error(
        self, reservation: Reservation, model: str, error: errors.APIError | httpx.HTTPError
    ) -> None:
        with self.condition:
            now = time.monotonic()
            code = getattr(error, "code", None)
            if code == 429:
                delay = 60.0
                response = getattr(error, "response", None)
                if response is not None:
                    try:
                        delay = max(delay, float(response.headers.get("Retry-After", "60")))
                    except (TypeError, ValueError):
                        try:
                            reset = parsedate_to_datetime(response.headers.get("Retry-After", ""))
                            delay = max(delay, reset.timestamp() - time.time())
                        except (TypeError, ValueError, OverflowError):
                            pass
                for detail in error_details(error):
                    retry = detail.get("retryDelay", "")
                    if isinstance(retry, str) and retry.endswith("s"):
                        try:
                            delay = max(delay, float(retry[:-1]))
                        except ValueError:
                            pass
                    violations = detail.get("violations", [])
                    for violation in violations if isinstance(violations, list) else []:
                        if not isinstance(violation, dict):
                            continue
                        quota = str(violation.get("quotaId", "")).lower()
                        if "perday" in quota or "daily" in quota:
                            reservation.budget.daily_requests = reservation.budget.rpd
                if not math.isfinite(delay):
                    delay = 60.0
                reservation.budget.cooldown_until = max(
                    reservation.budget.cooldown_until, now + delay
                )
            elif code == 402:
                # Billing exhaustion is project-wide; don't immediately try a sibling key.
                for credential in self.credentials:
                    if credential.project == reservation.credential.project:
                        credential.disabled = True
            elif code == 401 or (code == 400 and invalid_api_key(error)):
                reservation.credential.disabled = True
            elif code in {403, 404}:
                # Access can differ by model/account; don't disable an otherwise working key.
                reservation.credential.blocked_models.add(model)
            else:
                reservation.credential.cooldown_until = now + 2

    def call(
        self,
        model: str,
        texts: list[str],
        deadline: float,
        operation: Callable[[genai.Client, int], T],
        request_timeout_seconds: int | None = None,
    ) -> T:
        tried: set[str] = set()
        for _ in self.credentials:
            reservation = self.acquire(model, estimate_input_tokens(texts), deadline, tried)
            key = reservation.credential
            tried.add(key.name)
            try:
                remaining_ms = max(
                    1,
                    int(
                        min(
                            deadline - time.monotonic(),
                            request_timeout_seconds
                            if request_timeout_seconds is not None
                            else self.settings.embedding_timeout_seconds,
                        )
                        * 1000
                    ),
                )
                with genai.Client(
                    enterprise=False,
                    vertexai=False,
                    api_key=key.secret.get_secret_value(),
                    http_options=types.HttpOptions(
                        timeout=remaining_ms,
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                ) as client:
                    return operation(client, remaining_ms)
            except (errors.APIError, httpx.HTTPError) as error:
                code = getattr(error, "code", None)
                if code == 400 and not invalid_api_key(error):
                    raise GeminiError(
                        "Gemini rejected the request; check model, key and input configuration"
                    ) from None
                self.on_error(reservation, model, error)
                # No raw provider errors, submitted text or secrets are logged/returned.
            finally:
                self.release(reservation)
        if not any(
            not key.disabled and model not in key.blocked_models for key in self.credentials
        ):
            raise GeminiError("No configured credential can access this Gemini model")
        raise GeminiBusy(self.retry_after(model, estimate_input_tokens(texts)))


_pool: GeminiPool | None = None
_pool_lock = threading.Lock()


def get_gemini_pool() -> GeminiPool:
    # lru_cache alone can execute its factory twice on concurrent first requests.
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = GeminiPool(get_settings())
        return _pool
