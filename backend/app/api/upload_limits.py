"""Bound multipart request bytes before parser spooling, including chunked requests."""

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings

BODY_LIMIT_DETAIL = "PDF upload request exceeds size limit"


class UploadLimitMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"].rstrip("/") != "/api/v1/admin/documents"
        ):
            await self.app(scope, receive, send)
            return
        maximum = get_settings().max_upload_mb * 1024 * 1024 + 16 * 1024
        headers = dict(scope["headers"])
        try:
            size = int(headers.get(b"content-length", b"0"))
            if size < 0:
                raise ValueError
        except ValueError:
            await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(
                scope, receive, send
            )
            return
        if size > maximum:
            await JSONResponse({"detail": BODY_LIMIT_DETAIL}, status_code=413)(scope, receive, send)
            return
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > maximum:
                    # Multipart parser closes partially spooled files on MultiPartException.
                    raise MultiPartException(BODY_LIMIT_DETAIL)
            return message

        await self.app(scope, limited_receive, send)
