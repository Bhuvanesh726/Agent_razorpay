"""Agent-readable catalog endpoints — no chat, no policy engine, just data.
A consuming agent doesn't need an LLM call to find out what's for sale.
"""

from datetime import timezone
from email.utils import format_datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.catalog import CatalogFeedOut
from app.services import catalog_service

router = APIRouter(tags=["catalog"])


@router.get("/.well-known/catalog.json")
def discovery_doc(request: Request) -> dict:
    base_url = str(request.base_url).rstrip("/")
    return catalog_service.build_discovery_doc(base_url)


@router.get("/api/catalog/feed", response_model=CatalogFeedOut)
def catalog_feed(
    request: Request,
    response: Response,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
) -> CatalogFeedOut | Response:
    result = catalog_service.build_feed(db, page=page, page_size=page_size)

    etag = f'"{result.etag}"'
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip('"') == result.etag:
        # Returning a raw Response bypasses response_model validation, which
        # is what we want here — a 304 has no body to validate against
        # CatalogFeedOut in the first place.
        return Response(status_code=304, headers={"ETag": etag})

    response.headers["ETag"] = etag
    if result.last_modified is not None:
        # SQLite round-trips a DateTime(timezone=True) column back as naive
        # (it stores the value but doesn't enforce awareness) — pin to UTC
        # explicitly rather than let a database quirk make this a
        # per-backend bug in an HTTP caching header.
        last_modified = result.last_modified
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        response.headers["Last-Modified"] = format_datetime(last_modified, usegmt=True)
    response.headers["Cache-Control"] = "public, max-age=60"
    return result.body
