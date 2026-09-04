"""A 500 must reach the browser with its CORS headers, or the frontend cannot
read it and reports a working backend as unreachable.

See app/core/errors.py for why Starlette's own ServerErrorMiddleware cannot do
this, and Failures.md for the incident that motivated it.
"""

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import CORSSafeServerErrorMiddleware
from app.main import app

_ORIGIN = settings.frontend_url

_boom = APIRouter()


@_boom.get("/__test__/boom")
def boom():
    raise RuntimeError("deliberate explosion")


@pytest.fixture()
def client():
    app.include_router(_boom)
    try:
        # raise_server_exceptions=False makes TestClient behave like a real
        # browser client: it returns the 500 response instead of re-raising
        # the exception into the test, which is the whole thing under test.
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/__test__/boom"]


def test_unhandled_exception_returns_500_with_cors_headers(client):
    res = client.get("/__test__/boom", headers={"Origin": _ORIGIN})

    assert res.status_code == 500
    # The actual regression: without a CORS header the browser blocks the
    # response body entirely and fetch() rejects, so the frontend can only
    # report a connectivity failure for a backend that answered.
    assert res.headers.get("access-control-allow-origin") == _ORIGIN


def test_unhandled_exception_body_is_readable_json(client):
    res = client.get("/__test__/boom", headers={"Origin": _ORIGIN})

    body = res.json()
    # Same `detail` shape as FastAPI's HTTPException, so frontend/src/lib/api.ts
    # surfaces it through its existing path rather than a special case.
    assert "detail" in body
    assert body["error_type"] == "RuntimeError"


def test_successful_responses_still_carry_cors_headers(client):
    """The error middleware sits in the hot path for every request; it must
    not disturb the ordinary case."""
    res = client.get("/health", headers={"Origin": _ORIGIN})

    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == _ORIGIN


def test_error_middleware_is_registered_inside_cors():
    """Ordering is the entire fix. If CORSMiddleware is ever registered before
    the error middleware, 500s silently lose their CORS headers again and the
    only symptom is a misleading frontend message — so pin the order here.

    Starlette treats the last-registered middleware as the outermost, and
    `user_middleware` is stored outermost-first.
    """
    classes = [m.cls for m in app.user_middleware]

    assert CORSMiddleware in classes, "CORS middleware is not registered at all"
    assert CORSSafeServerErrorMiddleware in classes, "error middleware is not registered at all"
    assert classes.index(CORSMiddleware) < classes.index(CORSSafeServerErrorMiddleware), (
        "CORSSafeServerErrorMiddleware must sit inside CORSMiddleware — register it "
        "BEFORE CORSMiddleware in app/main.py"
    )
