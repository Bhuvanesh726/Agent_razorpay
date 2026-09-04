"""Turn unhandled exceptions into a real HTTP response *inside* the CORS
middleware, so the browser can read them.

The problem this solves: Starlette installs `ServerErrorMiddleware` as the
outermost layer of the stack, above every middleware added with
`app.add_middleware` — CORSMiddleware included. When a request handler raises,
the exception propagates past CORSMiddleware as a Python exception rather than
as a response, so CORSMiddleware never gets to attach
`Access-Control-Allow-Origin`, and ServerErrorMiddleware writes its bare 500
straight to the raw outer `send`.

The browser then refuses to expose that response to JavaScript at all. The
`fetch` rejects, and frontend/src/lib/api.ts reports the only thing it can
see — "Could not reach the API. Is the backend running?" — for a backend that
is running fine and just returned a 500. Every real error in this application
was being reported to the user as a connectivity problem: the same class of
defect as a log formatter that swallows tracebacks, where the diagnostic is
destroyed on the way to the person who needs it.

The fix is to catch the exception below CORSMiddleware and return an ordinary
JSONResponse. Because it is a response and not an exception, it travels back
out through CORSMiddleware normally and arrives with its CORS headers intact,
so the frontend can read the status and the message.

Registration order matters and is asserted in tests: this must be added
*before* CORSMiddleware in app/main.py, since Starlette treats the
last-registered middleware as the outermost.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.logging import logger


class CORSSafeServerErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            # request_id is set by RequestLoggingMiddleware, which runs
            # inside this one and shares the same ASGI scope, so it is
            # already populated by the time we get here. Defensive anyway:
            # an exception raised before it is set must not become a second
            # exception inside the error handler.
            request_id = getattr(request.state, "request_id", None)

            # ServerErrorMiddleware would normally be what logs this. It no
            # longer sees the exception, so the traceback has to be recorded
            # here or it is lost entirely.
            logger.error(
                "unhandled exception",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )

            return JSONResponse(
                status_code=500,
                content={
                    # Same `detail` shape FastAPI's HTTPException produces, so
                    # the frontend's existing error handling reads it without
                    # a special case.
                    "detail": "Something went wrong on the server. This has been logged.",
                    "error_type": type(e).__name__,
                    "request_id": request_id,
                },
                headers={"x-request-id": request_id} if request_id else None,
            )
