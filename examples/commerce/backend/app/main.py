"""Application entry point (generated)."""

import importlib
import pkgutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import custom_routers
from app.auth.config import get_auth_settings
from app.auth.middleware import SecurityHeadersMiddleware
from app.auth.provider_lock import ensure_provider_lock
from app.auth.router import router as _auth_router
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import RequestIdMiddleware, configure_logging
from app.db import engine
from app.routers._health import router as _health_router
from app.routers.articles import router as articles_router
from app.routers.blogs import router as blogs_router
from app.routers.cart_lines import router as cart_lines_router
from app.routers.carts import router as carts_router
from app.routers.collections import router as collections_router
from app.routers.customer_addresses import router as customer_addresses_router
from app.routers.customers import router as customers_router
from app.routers.discount_usages import router as discount_usages_router
from app.routers.discounts import router as discounts_router
from app.routers.fulfillment_lines import router as fulfillment_lines_router
from app.routers.fulfillments import router as fulfillments_router
from app.routers.gift_cards import router as gift_cards_router
from app.routers.inventory_levels import router as inventory_levels_router
from app.routers.locations import router as locations_router
from app.routers.metafields import router as metafields_router
from app.routers.order_events import router as order_events_router
from app.routers.order_lines import router as order_lines_router
from app.routers.orders import router as orders_router
from app.routers.pages import router as pages_router
from app.routers.product_images import router as product_images_router
from app.routers.products import router as products_router
from app.routers.refund_lines import router as refund_lines_router
from app.routers.refunds import router as refunds_router
from app.routers.reviews import router as reviews_router
from app.routers.shipping_rates import router as shipping_rates_router
from app.routers.shipping_zones import router as shipping_zones_router
from app.routers.stores import router as stores_router
from app.routers.tags import router as tags_router
from app.routers.tax_rates import router as tax_rates_router
from app.routers.transactions import router as transactions_router
from app.routers.variants import router as variants_router
from app.routers.webhooks import router as webhooks_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_auth_settings()  # a missing secret stops the app here, with a clear message
    await ensure_provider_lock()  # refuses to start on a database used by another provider
    yield
    await engine.dispose()


def include_custom_routers(app: FastAPI) -> None:
    """Mount every module in app/custom_routers that defines a `router`."""
    for module_info in sorted(pkgutil.iter_modules(custom_routers.__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{custom_routers.__name__}.{module_info.name}")
        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title='Commerce', version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(_health_router)
    app.include_router(_auth_router)
    app.include_router(articles_router)
    app.include_router(blogs_router)
    app.include_router(cart_lines_router)
    app.include_router(carts_router)
    app.include_router(collections_router)
    app.include_router(customer_addresses_router)
    app.include_router(customers_router)
    app.include_router(discount_usages_router)
    app.include_router(discounts_router)
    app.include_router(fulfillment_lines_router)
    app.include_router(fulfillments_router)
    app.include_router(gift_cards_router)
    app.include_router(inventory_levels_router)
    app.include_router(locations_router)
    app.include_router(metafields_router)
    app.include_router(order_events_router)
    app.include_router(order_lines_router)
    app.include_router(orders_router)
    app.include_router(pages_router)
    app.include_router(product_images_router)
    app.include_router(products_router)
    app.include_router(refund_lines_router)
    app.include_router(refunds_router)
    app.include_router(reviews_router)
    app.include_router(shipping_rates_router)
    app.include_router(shipping_zones_router)
    app.include_router(stores_router)
    app.include_router(tags_router)
    app.include_router(tax_rates_router)
    app.include_router(transactions_router)
    app.include_router(variants_router)
    app.include_router(webhooks_router)
    include_custom_routers(app)
    return app


app = create_app()
