from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.routers import agent, audit, campaigns, cart, catalog, health, payments, products
from app.testing.chaos import ChaosHeaderMiddleware

configure_logging()

app = FastAPI(title=settings.app_name)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(ChaosHeaderMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
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
