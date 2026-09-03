from fastapi import APIRouter

from app.auth.routing import SecureAPIRoute, public

router = APIRouter(tags=["health"], route_class=SecureAPIRoute)


@router.get("/health")
@public
def health() -> dict[str, str]:
    return {"status": "ok"}
