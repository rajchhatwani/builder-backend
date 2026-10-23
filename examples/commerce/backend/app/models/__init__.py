"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.articles import Article
from app.models.blogs import Blog
from app.models.cart_lines import CartLine
from app.models.carts import Cart
from app.models.collections import Collection
from app.models.customer_addresses import CustomerAddress
from app.models.customers import Customer
from app.models.discount_usages import DiscountUsage
from app.models.discounts import Discount
from app.models.fulfillment_lines import FulfillmentLine
from app.models.fulfillments import Fulfillment
from app.models.gift_cards import GiftCard
from app.models.inventory_levels import InventoryLevel
from app.models.locations import Location
from app.models.metafields import Metafield
from app.models.order_events import OrderEvent
from app.models.order_lines import OrderLine
from app.models.orders import Order
from app.models.pages import Page
from app.models.product_images import ProductImage
from app.models.products import Product
from app.models.refund_lines import RefundLine
from app.models.refunds import Refund
from app.models.reviews import Review
from app.models.shipping_rates import ShippingRate
from app.models.shipping_zones import ShippingZone
from app.models.stores import Store
from app.models.tags import Tag
from app.models.tax_rates import TaxRate
from app.models.transactions import Transaction
from app.models.variants import Variant
from app.models.webhooks import Webhook

__all__ = [
    "Base",
    "Article",
    "Blog",
    "CartLine",
    "Cart",
    "Collection",
    "CustomerAddress",
    "Customer",
    "DiscountUsage",
    "Discount",
    "FulfillmentLine",
    "Fulfillment",
    "GiftCard",
    "InventoryLevel",
    "Location",
    "Metafield",
    "OrderEvent",
    "OrderLine",
    "Order",
    "Page",
    "ProductImage",
    "Product",
    "RefundLine",
    "Refund",
    "Review",
    "ShippingRate",
    "ShippingZone",
    "Store",
    "Tag",
    "TaxRate",
    "Transaction",
    "Variant",
    "Webhook",
    "_associations",
    "_auth_models",
]
