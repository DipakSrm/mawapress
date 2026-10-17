"""Request body caps, enforced before any route (and so before auth or multipart parsing) reads the body."""

import json

DEFAULT_LIMIT = 1024 * 1024
OVERHEAD = 1024 * 1024  # multipart framing around the file itself
# path -> max body bytes
PATH_LIMITS = {
    "/api/media": 10 * 1024 * 1024 + OVERHEAD,
    "/api/import/docx": 15 * 1024 * 1024 + OVERHEAD,
}

_BODY = json.dumps(
    {"error": {"code": "FILE_TOO_LARGE", "message": "Request body is too large", "details": {}}}
).encode()


class _TooLarge(Exception):
    pass


def limit_for(path: str) -> int:
    return PATH_LIMITS.get(path.rstrip("/") or "/", DEFAULT_LIMIT)


class BodyLimitMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = limit_for(scope["path"])
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._reject(send)
            return

        received = 0
        started = False
        exceeded = False

        async def counting_receive():
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:  # chunked, or a Content-Length that lied
                    exceeded = True
                    raise _TooLarge
            return message

        async def tracking_send(message):
            nonlocal started
            if exceeded:
                # FastAPI turns a failed body read into its own 400/422; the real answer is 413.
                if not started:
                    started = True
                    await self._reject(send)
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not started:
                started = True
                await self._reject(send)

    @staticmethod
    async def _reject(send) -> None:
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(_BODY)).encode())],
        })
        await send({"type": "http.response.body", "body": _BODY})
