from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.auth import credentials_router, oauth_router, onboarding_router
from app.core.config import settings
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.routers import (
    agent,
    audit,
    campaigns,
    cart,
    catalog,
    checkout,
    dashboard,
    health,
    merchant,
    orders,
    payments,
    products,
)
from app.testing.chaos import ChaosHeaderMiddleware

configure_logging()

app = FastAPI(title=settings.app_name)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(ChaosHeaderMiddleware)
# Required by authlib's Starlette OAuth client to hold state/nonce across
# the Google redirect round-trip — unrelated to this backend's own JWTs
# (app/auth/security.py), which are stateless and never touch this session.
app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret_key)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(products.router)
app.include_router(cart.router)
app.include_router(agent.router)
app.include_router(audit.router)
app.include_router(payments.router)
app.include_router(catalog.router)
app.include_router(campaigns.router)
app.include_router(oauth_router.router)
app.include_router(credentials_router.router)
app.include_router(onboarding_router.router)
app.include_router(dashboard.router)
app.include_router(merchant.router)
app.include_router(checkout.router)
app.include_router(orders.router)
