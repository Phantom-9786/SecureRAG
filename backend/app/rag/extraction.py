import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from app.core.config import Settings


class PDFProcessingError(ValueError):
    """Safe user-facing extraction error; never includes parser internals or extracted text."""


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_pages(path: Path, settings: Settings) -> list[PageText]:
    try:
        with path.open("rb") as source:
            reader = PdfReader(source, strict=False)
            if reader.is_encrypted:
                raise PDFProcessingError("Encrypted PDFs are not supported in V1")
            if not 0 < len(reader.pages) <= settings.max_pdf_pages:
                raise PDFProcessingError("PDF has no pages or exceeds the page limit")
            pages = []
            total = 0
            for page_number, page in enumerate(reader.pages, start=1):
                stream = page.get_contents()
                if stream is not None and len(stream.get_data()) > settings.max_page_stream_bytes:
                    raise PDFProcessingError("PDF page content exceeds the processing limit")
                content = clean_text(page.extract_text() or "")
                total += len(content)
                if total > settings.max_document_characters:
                    raise PDFProcessingError("Extracted text exceeds the document limit")
                if content:
                    pages.append(PageText(page_number=page_number, text=content))
            if not pages:
                raise PDFProcessingError("No extractable text found; scanned PDFs require OCR")
            return pages
    except PDFProcessingError:
        raise
    except Exception:  # noqa: BLE001 -- untrusted parser failures must not expose extracted text
        raise PDFProcessingError("PDF could not be read; upload a valid text-based PDF") from None
