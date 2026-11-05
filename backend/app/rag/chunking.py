"""Page-aware, Unicode-safe chunks with a conservative UTF-8 byte budget."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from app.rag.extraction import PageText, PDFProcessingError

CHUNK_BYTES = 2000
OVERLAP_BYTES = 300


@dataclass(frozen=True)
class TextChunk:
    page_number: int
    content: str


def chunk_pages(pages: list[PageText], max_chunks: int) -> list[TextChunk]:
    chunks = []
    for page in pages:
        text = page.text
        # Cumulative byte offsets let us bound size without slicing through UTF-8 characters.
        offsets = [0]
        for char in text:
            offsets.append(offsets[-1] + len(char.encode("utf-8")))
        start = 0
        while start < len(text):
            end = bisect_right(offsets, offsets[start] + CHUNK_BYTES) - 1
            if end < len(text):
                lower = start + (end - start) // 2
                for separator in ("\n\n", "\n", ". ", " "):
                    boundary = text.rfind(separator, lower, end)
                    if boundary >= lower:
                        end = boundary + len(separator)
                        break
            content = text[start:end].strip()
            if content:
                chunks.append(TextChunk(page_number=page.page_number, content=content))
                if len(chunks) > max_chunks:
                    raise PDFProcessingError("PDF exceeds the maximum number of chunks")
            if end == len(text):
                break
            start = max(start + 1, bisect_left(offsets, offsets[end] - OVERLAP_BYTES))
    return chunks
