"""Private filesystem storage. No user-supplied filename is used as a storage path."""

import re
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import get_settings


class PDFStorage:
    def __init__(self, root: Path, max_bytes: int):
        self.root = root.resolve()
        self.max_bytes = max_bytes

    def path_for(self, key: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{32}\.pdf", key) is None:
            raise ValueError("Invalid storage key")
        path = (self.root / key).resolve()
        if path.parent != self.root:
            raise ValueError("Storage path is outside the private root")
        return path

    def save(
        self, source: BinaryIO, filename: str | None, content_type: str | None
    ) -> tuple[str, str]:
        name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if (
            not name.lower().endswith(".pdf")
            or len(name) > 255
            or any(ord(char) < 32 for char in name)
        ):
            raise HTTPException(status_code=415, detail="Upload a PDF with a valid filename")
        if content_type not in {"application/pdf", "application/octet-stream"}:
            raise HTTPException(status_code=415, detail="Upload a PDF file")
        source.seek(0)
        if source.read(5) != b"%PDF-":
            raise HTTPException(status_code=415, detail="File does not have a PDF header")
        source.seek(0)
        self.root.mkdir(parents=True, exist_ok=True)
        key = uuid4().hex + ".pdf"
        path = self.path_for(key)
        created = False
        try:
            with path.open("xb") as output:
                created = True
                size = 0
                while data := source.read(64 * 1024):
                    size += len(data)
                    if size > self.max_bytes:
                        raise HTTPException(status_code=413, detail="PDF exceeds upload size limit")
                    output.write(data)
        except BaseException:
            if created:
                path.unlink(missing_ok=True)
            raise
        return key, name

    def remove(self, key: str) -> None:
        self.path_for(key).unlink(missing_ok=True)


def get_storage() -> PDFStorage:
    settings = get_settings()
    return PDFStorage(settings.pdf_storage_root, settings.max_upload_mb * 1024 * 1024)
