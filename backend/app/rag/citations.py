"""Bounded source context and validation of model references against retrieved sources."""

import json
import re
from dataclasses import dataclass

from app.rag.retrieval import RetrievedChunk
from app.schemas.conversations import CitationOut

NO_EVIDENCE = "I couldn't find enough information in the documents available to you."
WITHHELD_ANSWER = (
    "This answer is unavailable because its supporting documents are no longer accessible."
)


class GroundingError(ValueError):
    pass


@dataclass(frozen=True)
class ContextSource:
    number: int
    chunk: RetrievedChunk

    def citation(self) -> CitationOut:
        return CitationOut(
            source_id=f"S{self.number}",
            document_id=self.chunk.document_id,
            chunk_id=self.chunk.chunk_id,
            document_title=self.chunk.document_title,
            filename=self.chunk.filename,
            page_number=self.chunk.page_number,
            download_url=f"/api/v1/documents/{self.chunk.document_id}/file",
        )


def build_context(chunks: list[RetrievedChunk], max_bytes: int) -> tuple[str, list[ContextSource]]:
    lines = []
    sources = []
    used = 0
    for chunk in chunks:
        number = len(sources) + 1
        line = json.dumps(
            {
                "source_id": f"S{number}",
                "document": chunk.document_title,
                "filename": chunk.filename,
                "page": chunk.page_number,
                "text": chunk.content,
            },
            ensure_ascii=False,
        )
        cost = len(line.encode("utf-8")) + (1 if lines else 0)
        if used + cost > max_bytes:
            continue  # Preserve full chunks rather than silently truncating the evidence.
        lines.append(line)
        sources.append(ContextSource(number, chunk))
        used += cost
    return "\n".join(lines), sources


def referenced_sources(answer: str, available: set[int]) -> list[int]:
    if answer.strip() == NO_EVIDENCE:
        return []
    if not answer.strip() or len(answer.encode("utf-8")) > 20000:
        raise GroundingError("Invalid answer size")
    references = re.findall(r"\[S([^\]\r\n]*)\]", answer)
    if not references:
        raise GroundingError("Answer has no source references")
    numbers = []
    for label in references:
        if not re.fullmatch(r"[1-9][0-9]*", label) or len(label) > 4:
            raise GroundingError("Invalid source label")
        number = int(label)
        if number not in available:
            raise GroundingError("Answer references an unavailable source")
        if number not in numbers:
            numbers.append(number)
    return numbers
