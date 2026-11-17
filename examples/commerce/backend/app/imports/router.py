"""Import / export routes (generated).

POST /<entity>/import      multipart `file` (+ optional `mapping` JSON: field -> csv header, `?dry_run=true`).
GET  /<entity>/export.csv  the readable fields of the rows the caller may list.

Import has the same caller access as the entity's create operation, export the same as its list operation (roles,
tenant, owner / row scope, policy). Fields the caller may not write are refused per row; fields the caller may not
read are not exported and not echoed. Text cells of an export are neutralized against spreadsheet formulas."""

import csv
import datetime as dt
import decimal
import io
import json
import typing as _t

import fastapi as _fa
import sqlalchemy as sa
from fastapi.routing import APIRoute as _APIRoute

from app import db as _db
from app.auth import access as _access
from app.core.errors import AppError
from app.crud.articles import ArticleRepository
from app.crud.blogs import BlogRepository
from app.crud.cart_lines import CartLineRepository
from app.crud.carts import CartRepository
from app.crud.collections import CollectionRepository
from app.crud.customer_addresses import CustomerAddressRepository
from app.crud.customers import CustomerRepository
from app.crud.discount_usages import DiscountUsageRepository
from app.crud.discounts import DiscountRepository
from app.crud.fulfillment_lines import FulfillmentLineRepository
from app.crud.fulfillments import FulfillmentRepository
from app.crud.gift_cards import GiftCardRepository
from app.crud.inventory_levels import InventoryLevelRepository
from app.crud.locations import LocationRepository
from app.crud.metafields import MetafieldRepository
from app.crud.order_events import OrderEventRepository
from app.crud.order_lines import OrderLineRepository
from app.crud.orders import OrderRepository
from app.crud.pages import PageRepository
from app.crud.product_images import ProductImageRepository
from app.crud.products import ProductRepository
from app.crud.refund_lines import RefundLineRepository
from app.crud.refunds import RefundRepository
from app.crud.reviews import ReviewRepository
from app.crud.shipping_rates import ShippingRateRepository
from app.crud.shipping_zones import ShippingZoneRepository
from app.crud.stores import StoreRepository
from app.crud.tags import TagRepository
from app.crud.tax_rates import TaxRateRepository
from app.crud.transactions import TransactionRepository
from app.crud.variants import VariantRepository
from app.crud.webhooks import WebhookRepository
from app.imports import csv_import as _ci
from app.imports import service as _service
from app.imports.fields import ENTITIES as _FIELDS
from app.routers.articles import _ACCESS as _ACCESS_articles
from app.routers.blogs import _ACCESS as _ACCESS_blogs
from app.routers.cart_lines import _ACCESS as _ACCESS_cart_lines
from app.routers.carts import _ACCESS as _ACCESS_carts
from app.routers.collections import _ACCESS as _ACCESS_collections
from app.routers.customer_addresses import _ACCESS as _ACCESS_customer_addresses
from app.routers.customers import _ACCESS as _ACCESS_customers
from app.routers.discount_usages import _ACCESS as _ACCESS_discount_usages
from app.routers.discounts import _ACCESS as _ACCESS_discounts
from app.routers.fulfillment_lines import _ACCESS as _ACCESS_fulfillment_lines
from app.routers.fulfillments import _ACCESS as _ACCESS_fulfillments
from app.routers.gift_cards import _ACCESS as _ACCESS_gift_cards
from app.routers.inventory_levels import _ACCESS as _ACCESS_inventory_levels
from app.routers.locations import _ACCESS as _ACCESS_locations
from app.routers.metafields import _ACCESS as _ACCESS_metafields
from app.routers.order_events import _ACCESS as _ACCESS_order_events
from app.routers.order_lines import _ACCESS as _ACCESS_order_lines
from app.routers.orders import _ACCESS as _ACCESS_orders
from app.routers.pages import _ACCESS as _ACCESS_pages
from app.routers.product_images import _ACCESS as _ACCESS_product_images
from app.routers.products import _ACCESS as _ACCESS_products
from app.routers.refund_lines import _ACCESS as _ACCESS_refund_lines
from app.routers.refunds import _ACCESS as _ACCESS_refunds
from app.routers.reviews import _ACCESS as _ACCESS_reviews
from app.routers.shipping_rates import _ACCESS as _ACCESS_shipping_rates
from app.routers.shipping_zones import _ACCESS as _ACCESS_shipping_zones
from app.routers.stores import _ACCESS as _ACCESS_stores
from app.routers.tags import _ACCESS as _ACCESS_tags
from app.routers.tax_rates import _ACCESS as _ACCESS_tax_rates
from app.routers.transactions import _ACCESS as _ACCESS_transactions
from app.routers.variants import _ACCESS as _ACCESS_variants
from app.routers.webhooks import _ACCESS as _ACCESS_webhooks
from app.schemas.articles import ArticleCreate
from app.schemas.blogs import BlogCreate
from app.schemas.cart_lines import CartLineCreate
from app.schemas.carts import CartCreate
from app.schemas.collections import CollectionCreate
from app.schemas.customer_addresses import CustomerAddressCreate
from app.schemas.customers import CustomerCreate
from app.schemas.discount_usages import DiscountUsageCreate
from app.schemas.discounts import DiscountCreate
from app.schemas.fulfillment_lines import FulfillmentLineCreate
from app.schemas.fulfillments import FulfillmentCreate
from app.schemas.gift_cards import GiftCardCreate
from app.schemas.inventory_levels import InventoryLevelCreate
from app.schemas.locations import LocationCreate
from app.schemas.metafields import MetafieldCreate
from app.schemas.order_events import OrderEventCreate
from app.schemas.order_lines import OrderLineCreate
from app.schemas.orders import OrderCreate
from app.schemas.pages import PageCreate
from app.schemas.product_images import ProductImageCreate
from app.schemas.products import ProductCreate
from app.schemas.refund_lines import RefundLineCreate
from app.schemas.refunds import RefundCreate
from app.schemas.reviews import ReviewCreate
from app.schemas.shipping_rates import ShippingRateCreate
from app.schemas.shipping_zones import ShippingZoneCreate
from app.schemas.stores import StoreCreate
from app.schemas.tags import TagCreate
from app.schemas.tax_rates import TaxRateCreate
from app.schemas.transactions import TransactionCreate
from app.schemas.variants import VariantCreate
from app.schemas.webhooks import WebhookCreate


class _BodyLimitRoute(_APIRoute):
    """Refuses an oversized upload BEFORE Starlette spools the multipart body to disk: a declared Content-Length
    over the cap is answered at once, and a body that streams more than the cap (chunked, or a lying header)
    is cut off while it is read. Answer: 413 import_too_large."""

    def get_route_handler(self) -> _t.Callable[[_fa.Request], _t.Coroutine[_t.Any, _t.Any, _fa.Response]]:
        original = super().get_route_handler()

        async def handler(request: _fa.Request) -> _fa.Response:
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > BODY_LIMIT:
                raise _too_large()
            seen = 0
            exceeded = False

            async def receive() -> _t.Any:
                nonlocal seen, exceeded
                message = await request.receive()
                seen += len(message.get("body", b""))
                if seen > BODY_LIMIT:
                    exceeded = True
                    raise _TooLarge
                return message

            try:
                return await original(_fa.Request(request.scope, receive))
            except Exception:
                if exceeded:
                    raise _too_large() from None
                raise

        return handler


router = _fa.APIRouter(tags=["import"], route_class=_BodyLimitRoute)
EXPORT_ROW_CAP = 10000
BODY_LIMIT = _ci.MAX_BYTES + 256 * 1024  # the file cap plus multipart framing and the mapping field


class _TooLarge(Exception):
    pass


def _too_large() -> AppError:
    return AppError("import_too_large", f"the file is larger than {_ci.MAX_BYTES} bytes", 413)
_EMPTY = frozenset[str]()


def _cell(value: object) -> object:
    """A CSV cell: text goes through neutralize_formula (see app/imports/csv_import.py); numbers stay numbers."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, int | float | decimal.Decimal):
        return str(value)
    if isinstance(value, dict | list):
        return _ci.neutralize_formula(json.dumps(value, ensure_ascii=False))
    return _ci.neutralize_formula(str(value))


async def _read_upload(file: _fa.UploadFile) -> bytes:
    data = await file.read(_ci.MAX_BYTES + 1)
    if len(data) > _ci.MAX_BYTES:
        raise AppError("import_too_large", f"the file is larger than {_ci.MAX_BYTES} bytes", 413)
    return data


@router.post("/articles/import", response_model=_service.ImportResult)
async def import_articles(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_articles["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Article rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = ArticleRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Article"],
        ArticleCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/articles/export.csv", response_class=_fa.Response)
async def export_articles(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_articles["list"])],
) -> _fa.Response:
    """Export Article as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = ArticleRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'title', 'handle', 'author', 'body_html', 'summary_html', 'published', 'published_at', 'tags_cache', 'blog_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="articles.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/blogs/import", response_model=_service.ImportResult)
async def import_blogs(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_blogs["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Blog rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = BlogRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Blog"],
        BlogCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/blogs/export.csv", response_class=_fa.Response)
async def export_blogs(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_blogs["list"])],
) -> _fa.Response:
    """Export Blog as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = BlogRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'title', 'handle', 'commentable', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="blogs.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/cart_lines/import", response_model=_service.ImportResult)
async def import_cart_lines(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_cart_lines["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import CartLine rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = CartLineRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["CartLine"],
        CartLineCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/cart_lines/export.csv", response_class=_fa.Response)
async def export_cart_lines(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_cart_lines["list"])],
) -> _fa.Response:
    """Export CartLine as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = CartLineRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'quantity', 'properties', 'cart_id', 'variant_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="cart_lines.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/carts/import", response_model=_service.ImportResult)
async def import_carts(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_carts["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Cart rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = CartRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Cart"],
        CartCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/carts/export.csv", response_class=_fa.Response)
async def export_carts(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_carts["list"])],
) -> _fa.Response:
    """Export Cart as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = CartRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'token', 'email', 'currency', 'status', 'discount_code', 'note', 'attributes', 'expires_at', 'customer_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="carts.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/collections/import", response_model=_service.ImportResult)
async def import_collections(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_collections["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Collection rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = CollectionRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Collection"],
        CollectionCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/collections/export.csv", response_class=_fa.Response)
async def export_collections(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_collections["list"])],
) -> _fa.Response:
    """Export Collection as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = CollectionRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'title', 'handle', 'description_html', 'kind', 'rules', 'sort_order', 'published', 'published_at', 'seo_title', 'seo_description', 'parent_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="collections.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/customer_addresses/import", response_model=_service.ImportResult)
async def import_customer_addresses(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_customer_addresses["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import CustomerAddress rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = CustomerAddressRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["CustomerAddress"],
        CustomerAddressCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/customer_addresses/export.csv", response_class=_fa.Response)
async def export_customer_addresses(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_customer_addresses["list"])],
) -> _fa.Response:
    """Export CustomerAddress as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = CustomerAddressRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'name', 'company', 'address1', 'address2', 'city', 'province', 'province_code', 'country', 'country_code', 'postal_code', 'phone', 'is_default', 'customer_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="customer_addresses.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/customers/import", response_model=_service.ImportResult)
async def import_customers(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_customers["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Customer rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = CustomerRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Customer"],
        CustomerCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/customers/export.csv", response_class=_fa.Response)
async def export_customers(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_customers["list"])],
) -> _fa.Response:
    """Export Customer as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = CustomerRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'email', 'first_name', 'last_name', 'phone', 'state', 'accepts_marketing', 'accepts_marketing_updated_at', 'tax_exempt', 'total_spent', 'orders_count', 'tags_cache', 'note', 'locale', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="customers.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/discount_usages/import", response_model=_service.ImportResult)
async def import_discount_usages(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_discount_usages["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import DiscountUsage rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = DiscountUsageRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["DiscountUsage"],
        DiscountUsageCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/discount_usages/export.csv", response_class=_fa.Response)
async def export_discount_usages(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_discount_usages["list"])],
) -> _fa.Response:
    """Export DiscountUsage as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = DiscountUsageRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'amount', 'email', 'discount_id', 'order_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="discount_usages.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/discounts/import", response_model=_service.ImportResult)
async def import_discounts(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_discounts["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Discount rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = DiscountRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Discount"],
        DiscountCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/discounts/export.csv", response_class=_fa.Response)
async def export_discounts(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_discounts["list"])],
) -> _fa.Response:
    """Export Discount as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = DiscountRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'code', 'title', 'kind', 'value', 'target', 'minimum_subtotal', 'usage_limit', 'once_per_customer', 'used_count', 'combines_with_other', 'applies_to', 'starts_at', 'ends_at', 'active', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="discounts.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/fulfillment_lines/import", response_model=_service.ImportResult)
async def import_fulfillment_lines(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_fulfillment_lines["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import FulfillmentLine rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = FulfillmentLineRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["FulfillmentLine"],
        FulfillmentLineCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/fulfillment_lines/export.csv", response_class=_fa.Response)
async def export_fulfillment_lines(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_fulfillment_lines["list"])],
) -> _fa.Response:
    """Export FulfillmentLine as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = FulfillmentLineRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'quantity', 'fulfillment_id', 'order_line_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="fulfillment_lines.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/fulfillments/import", response_model=_service.ImportResult)
async def import_fulfillments(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_fulfillments["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Fulfillment rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = FulfillmentRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Fulfillment"],
        FulfillmentCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/fulfillments/export.csv", response_class=_fa.Response)
async def export_fulfillments(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_fulfillments["list"])],
) -> _fa.Response:
    """Export Fulfillment as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = FulfillmentRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'status', 'tracking_company', 'tracking_number', 'tracking_url', 'notify_customer', 'shipped_at', 'location_id', 'order_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="fulfillments.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/gift_cards/import", response_model=_service.ImportResult)
async def import_gift_cards(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_gift_cards["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import GiftCard rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = GiftCardRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["GiftCard"],
        GiftCardCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/gift_cards/export.csv", response_class=_fa.Response)
async def export_gift_cards(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_gift_cards["list"])],
) -> _fa.Response:
    """Export GiftCard as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = GiftCardRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'code', 'initial_value', 'balance', 'currency', 'expires_on', 'disabled', 'note', 'customer_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="gift_cards.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/inventory_levels/import", response_model=_service.ImportResult)
async def import_inventory_levels(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_inventory_levels["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import InventoryLevel rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = InventoryLevelRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["InventoryLevel"],
        InventoryLevelCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/inventory_levels/export.csv", response_class=_fa.Response)
async def export_inventory_levels(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_inventory_levels["list"])],
) -> _fa.Response:
    """Export InventoryLevel as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = InventoryLevelRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'available', 'on_hand', 'committed', 'incoming', 'location_id', 'variant_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="inventory_levels.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/locations/import", response_model=_service.ImportResult)
async def import_locations(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_locations["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Location rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = LocationRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Location"],
        LocationCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/locations/export.csv", response_class=_fa.Response)
async def export_locations(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_locations["list"])],
) -> _fa.Response:
    """Export Location as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = LocationRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'name', 'active', 'fulfills_online_orders', 'address1', 'address2', 'city', 'province', 'province_code', 'country', 'country_code', 'postal_code', 'phone', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="locations.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/metafields/import", response_model=_service.ImportResult)
async def import_metafields(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_metafields["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Metafield rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = MetafieldRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Metafield"],
        MetafieldCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/metafields/export.csv", response_class=_fa.Response)
async def export_metafields(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_metafields["list"])],
) -> _fa.Response:
    """Export Metafield as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = MetafieldRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'owner_type', 'owner_id', 'namespace', 'key', 'value_type', 'value', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="metafields.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/order_events/import", response_model=_service.ImportResult)
async def import_order_events(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_order_events["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import OrderEvent rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = OrderEventRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["OrderEvent"],
        OrderEventCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/order_events/export.csv", response_class=_fa.Response)
async def export_order_events(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_order_events["list"])],
) -> _fa.Response:
    """Export OrderEvent as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = OrderEventRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'verb', 'message', 'actor', 'data', 'order_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="order_events.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/order_lines/import", response_model=_service.ImportResult)
async def import_order_lines(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_order_lines["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import OrderLine rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = OrderLineRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["OrderLine"],
        OrderLineCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/order_lines/export.csv", response_class=_fa.Response)
async def export_order_lines(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_order_lines["list"])],
) -> _fa.Response:
    """Export OrderLine as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = OrderLineRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'title', 'variant_title', 'sku', 'quantity', 'unit_price', 'discount_total', 'tax_total', 'fulfilled_quantity', 'refunded_quantity', 'properties', 'order_id', 'variant_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="order_lines.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/orders/import", response_model=_service.ImportResult)
async def import_orders(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_orders["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Order rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = OrderRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Order"],
        OrderCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/orders/export.csv", response_class=_fa.Response)
async def export_orders(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_orders["list"])],
) -> _fa.Response:
    """Export Order as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = OrderRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'number', 'email', 'status', 'financial_status', 'fulfillment_status', 'currency', 'subtotal', 'shipping_total', 'tax_total', 'discount_total', 'total', 'total_refunded', 'billing_address', 'shipping_address', 'shipping_method', 'discount_code', 'note', 'tags_cache', 'source', 'placed_at', 'closed_at', 'cancelled_at', 'cancel_reason', 'cart_id', 'customer_id', 'shipping_rate_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="orders.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/pages/import", response_model=_service.ImportResult)
async def import_pages(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_pages["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Page rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = PageRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Page"],
        PageCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/pages/export.csv", response_class=_fa.Response)
async def export_pages(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_pages["list"])],
) -> _fa.Response:
    """Export Page as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = PageRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'title', 'handle', 'body_html', 'published', 'template_suffix', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="pages.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/product_images/import", response_model=_service.ImportResult)
async def import_product_images(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_product_images["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import ProductImage rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = ProductImageRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["ProductImage"],
        ProductImageCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/product_images/export.csv", response_class=_fa.Response)
async def export_product_images(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_product_images["list"])],
) -> _fa.Response:
    """Export ProductImage as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = ProductImageRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'url', 'alt', 'position', 'width', 'height', 'product_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="product_images.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/products/import", response_model=_service.ImportResult)
async def import_products(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_products["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Product rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = ProductRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Product"],
        ProductCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/products/export.csv", response_class=_fa.Response)
async def export_products(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_products["list"])],
) -> _fa.Response:
    """Export Product as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = ProductRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'title', 'handle', 'description_html', 'vendor', 'product_type', 'status', 'tags_cache', 'options', 'published_at', 'seo_title', 'seo_description', 'requires_shipping', 'taxable', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="products.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/refund_lines/import", response_model=_service.ImportResult)
async def import_refund_lines(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_refund_lines["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import RefundLine rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = RefundLineRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["RefundLine"],
        RefundLineCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/refund_lines/export.csv", response_class=_fa.Response)
async def export_refund_lines(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_refund_lines["list"])],
) -> _fa.Response:
    """Export RefundLine as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = RefundLineRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'quantity', 'subtotal', 'order_line_id', 'refund_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="refund_lines.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/refunds/import", response_model=_service.ImportResult)
async def import_refunds(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_refunds["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Refund rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = RefundRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Refund"],
        RefundCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/refunds/export.csv", response_class=_fa.Response)
async def export_refunds(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_refunds["list"])],
) -> _fa.Response:
    """Export Refund as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = RefundRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'amount', 'reason', 'restock', 'note', 'order_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="refunds.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/reviews/import", response_model=_service.ImportResult)
async def import_reviews(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_reviews["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Review rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = ReviewRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Review"],
        ReviewCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/reviews/export.csv", response_class=_fa.Response)
async def export_reviews(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_reviews["list"])],
) -> _fa.Response:
    """Export Review as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = ReviewRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'rating', 'title', 'body', 'author_name', 'status', 'verified_purchase', 'customer_id', 'product_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="reviews.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/shipping_rates/import", response_model=_service.ImportResult)
async def import_shipping_rates(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_shipping_rates["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import ShippingRate rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = ShippingRateRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["ShippingRate"],
        ShippingRateCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/shipping_rates/export.csv", response_class=_fa.Response)
async def export_shipping_rates(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_shipping_rates["list"])],
) -> _fa.Response:
    """Export ShippingRate as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = ShippingRateRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'name', 'price', 'min_order_subtotal', 'min_weight', 'max_weight', 'active', 'zone_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="shipping_rates.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/shipping_zones/import", response_model=_service.ImportResult)
async def import_shipping_zones(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_shipping_zones["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import ShippingZone rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = ShippingZoneRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["ShippingZone"],
        ShippingZoneCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/shipping_zones/export.csv", response_class=_fa.Response)
async def export_shipping_zones(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_shipping_zones["list"])],
) -> _fa.Response:
    """Export ShippingZone as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = ShippingZoneRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'name', 'countries', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="shipping_zones.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/stores/import", response_model=_service.ImportResult)
async def import_stores(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_stores["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Store rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = StoreRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Store"],
        StoreCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/stores/export.csv", response_class=_fa.Response)
async def export_stores(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_stores["list"])],
) -> _fa.Response:
    """Export Store as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = StoreRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'name', 'legal_name', 'email', 'domain', 'currency', 'timezone', 'weight_unit', 'plan', 'password_protected', 'settings', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="stores.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/tags/import", response_model=_service.ImportResult)
async def import_tags(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_tags["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Tag rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = TagRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Tag"],
        TagCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/tags/export.csv", response_class=_fa.Response)
async def export_tags(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_tags["list"])],
) -> _fa.Response:
    """Export Tag as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = TagRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'name', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="tags.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/tax_rates/import", response_model=_service.ImportResult)
async def import_tax_rates(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_tax_rates["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import TaxRate rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = TaxRateRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["TaxRate"],
        TaxRateCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/tax_rates/export.csv", response_class=_fa.Response)
async def export_tax_rates(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_tax_rates["list"])],
) -> _fa.Response:
    """Export TaxRate as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = TaxRateRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'country_code', 'province_code', 'name', 'rate', 'includes_shipping', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="tax_rates.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/transactions/import", response_model=_service.ImportResult)
async def import_transactions(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_transactions["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Transaction rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = TransactionRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Transaction"],
        TransactionCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/transactions/export.csv", response_class=_fa.Response)
async def export_transactions(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_transactions["list"])],
) -> _fa.Response:
    """Export Transaction as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = TransactionRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'kind', 'status', 'amount', 'currency', 'gateway', 'reference', 'error_code', 'processed_at', 'order_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="transactions.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/variants/import", response_model=_service.ImportResult)
async def import_variants(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_variants["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Variant rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = VariantRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Variant"],
        VariantCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/variants/export.csv", response_class=_fa.Response)
async def export_variants(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_variants["list"])],
) -> _fa.Response:
    """Export Variant as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = VariantRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'title', 'sku', 'barcode', 'price', 'compare_at_price', 'cost', 'weight', 'position', 'option1', 'option2', 'option3', 'taxable', 'requires_shipping', 'inventory_policy', 'inventory_tracked', 'product_id', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="variants.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/webhooks/import", response_model=_service.ImportResult)
async def import_webhooks(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_webhooks["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Webhook rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = WebhookRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Webhook"],
        WebhookCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/webhooks/export.csv", response_class=_fa.Response)
async def export_webhooks(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_webhooks["list"])],
) -> _fa.Response:
    """Export Webhook as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = WebhookRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'topic', 'url', 'body_format', 'secret', 'active', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="webhooks.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
