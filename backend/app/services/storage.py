"""Private PDF storage using generated object keys."""

import re
from collections.abc import Callable
from contextlib import closing
from os import fdopen
from pathlib import Path
from tempfile import mkstemp
from typing import BinaryIO
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from app.core.config import Settings, get_settings


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

    def local_copy(self, key: str) -> tuple[Path, Callable[[], None] | None]:
        return self.path_for(key), None


class S3PDFStorage(PDFStorage):
    def __init__(self, settings: Settings):
        super().__init__(settings.pdf_storage_root, settings.max_upload_mb * 1024 * 1024)
        self.bucket = settings.pdf_s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.aws_endpoint_url_s3,
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.aws_secret_access_key.get_secret_value(),
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                connect_timeout=5,
                read_timeout=20,
                retries={"total_max_attempts": 2},
            ),
        )

    def save(
        self, source: BinaryIO, filename: str | None, content_type: str | None
    ) -> tuple[str, str]:
        key, name = super().save(source, filename, content_type)
        path = self.path_for(key)
        try:
            with path.open("rb") as body:
                self.client.put_object(
                    Bucket=self.bucket, Key=key, Body=body, ContentType="application/pdf"
                )
        except (BotoCoreError, ClientError):
            raise OSError("Private PDF storage is unavailable") from None
        finally:
            path.unlink(missing_ok=True)
        return key, name

    def local_copy(self, key: str) -> tuple[Path, Callable[[], None]]:
        self.path_for(key)  # Validate the persisted key before requesting the object.
        fd, filename = mkstemp(suffix=".pdf")
        path = Path(filename)
        try:
            with fdopen(fd, "wb") as output:
                response = self.client.get_object(Bucket=self.bucket, Key=key)
                with closing(response["Body"]) as body:
                    remaining = self.max_bytes
                    for chunk in body.iter_chunks(chunk_size=64 * 1024):
                        remaining -= len(chunk)
                        if remaining < 0:
                            raise OSError("Stored PDF exceeds upload size limit")
                        output.write(chunk)
        except BaseException as error:
            path.unlink(missing_ok=True)
            if isinstance(error, ClientError) and error.response["Error"]["Code"] in {
                "NoSuchKey",
                "404",
            }:
                raise FileNotFoundError("Stored PDF was not found") from None
            if isinstance(error, (BotoCoreError, ClientError)):
                raise OSError("Private PDF storage is unavailable") from None
            raise
        return path, lambda: path.unlink(missing_ok=True)

    def remove(self, key: str) -> None:
        self.path_for(key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError):
            raise OSError("Private PDF storage is unavailable") from None


def get_storage() -> PDFStorage:
    settings = get_settings()
    if settings.pdf_s3_bucket:
        return S3PDFStorage(settings)
    return PDFStorage(settings.pdf_storage_root, settings.max_upload_mb * 1024 * 1024)
