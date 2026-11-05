"""Explainable V1 routing, not a claim to predict question difficulty perfectly."""

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ModelDecision:
    tier: Literal["basic", "advanced"]
    reason: str


def choose_model_tier(
    question: str,
    context_characters: int,
    source_documents: int,
    mode: Literal["auto", "basic", "advanced"] = "auto",
) -> ModelDecision:
    if mode in {"basic", "advanced"}:
        return ModelDecision(mode, "Explicit model-tier selection")
    if mode != "auto":
        raise ValueError("Invalid routing mode")
    complex_intent = re.search(
        r"\b(compare|contrast|trade[- ]?offs?|reconcile|evaluate|analyse|analyze|"
        r"justify|versus|vs|step.by.step|multi.step)\b",
        question,
        flags=re.IGNORECASE,
    )
    if complex_intent:
        return ModelDecision(
            "advanced", "Comparison, analysis or multiple-step reasoning requested"
        )
    if source_documents >= 3:
        return ModelDecision("advanced", "Evidence spans multiple documents")
    if context_characters > 12000:
        return ModelDecision("advanced", "Large authorized evidence context")
    if question.count("?") >= 3:
        return ModelDecision("advanced", "Multiple questions require synthesis")
    return ModelDecision("basic", "Direct lookup or short grounded answer")
