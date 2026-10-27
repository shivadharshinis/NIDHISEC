"""Reject oversized upload requests before their body is read.

FastAPI parses multipart bodies before the endpoint runs, so the size limit is
checked here first, from the Content-Length header. The endpoint enforces the
exact per-file limit afterwards.
"""

import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Allowance for multipart boundaries and form fields around the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


class UploadSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_file_bytes: int, path_pattern: str) -> None:
        self.app = app
        self.max_body_bytes = max_file_bytes + MULTIPART_OVERHEAD_BYTES
        self.max_file_mb = max_file_bytes // (1024 * 1024)
        self.path_pattern = re.compile(path_pattern)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and self.path_pattern.fullmatch(scope["path"]):
            headers = dict(scope["headers"])
            length = headers.get(b"content-length")
            if length is None or not length.isdigit():
                response = JSONResponse({"detail": "Content-Length is required for uploads"}, status_code=411)
                await response(scope, receive, send)
                return
            if int(length) > self.max_body_bytes:
                response = JSONResponse(
                    {"detail": [{"loc": ["body", "file"], "msg": f"The file exceeds the {self.max_file_mb} MB limit", "type": "value_error"}]},
                    status_code=413,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
