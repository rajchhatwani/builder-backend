"""Search routes (generated): GET /<entity>/search?q=&limit= for entities with searchable fields.

Same caller access as the entity's list endpoint (roles, tenant, owner / row scope, policy). Fields the
caller may not read are not searched and not returned. Engine: SEARCH_BACKEND (see app/search/config.py)."""

import typing as _t

import fastapi as _fa

from app import db as _db
from app.auth import access as _access
from app.crud.articles import ArticleRepository
from app.crud.collections import CollectionRepository
from app.crud.customers import CustomerRepository
from app.crud.discounts import DiscountRepository
from app.crud.locations import LocationRepository
from app.crud.orders import OrderRepository
from app.crud.products import ProductRepository
from app.crud.reviews import ReviewRepository
from app.crud.tags import TagRepository
from app.crud.variants import VariantRepository
from app.routers.articles import _ACCESS as _ACCESS_articles
from app.routers.collections import _ACCESS as _ACCESS_collections
from app.routers.customers import _ACCESS as _ACCESS_customers
from app.routers.discounts import _ACCESS as _ACCESS_discounts
from app.routers.locations import _ACCESS as _ACCESS_locations
from app.routers.orders import _ACCESS as _ACCESS_orders
from app.routers.products import _ACCESS as _ACCESS_products
from app.routers.reviews import _ACCESS as _ACCESS_reviews
from app.routers.tags import _ACCESS as _ACCESS_tags
from app.routers.variants import _ACCESS as _ACCESS_variants
from app.schemas.articles import ArticleRead
from app.schemas.collections import CollectionRead
from app.schemas.customers import CustomerRead
from app.schemas.discounts import DiscountRead
from app.schemas.locations import LocationRead
from app.schemas.orders import OrderRead
from app.schemas.products import ProductRead
from app.schemas.reviews import ReviewRead
from app.schemas.tags import TagRead
from app.schemas.variants import VariantRead
from app.search import service as _service

router = _fa.APIRouter(tags=["search"])
_Q = _t.Annotated[str, _fa.Query(min_length=1, max_length=200, description="Words to look for")]
_LIMIT = _t.Annotated[int, _fa.Query(ge=1, le=100)]


@router.get(
    "/articles/search",
    response_model=_service.SearchPage[ArticleRead],
)
async def search_articles(
    session: _db.SessionDep,
    q: _Q,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_articles["list"])],
    limit: _LIMIT = 20,
) -> _service.SearchPage[ArticleRead]:
    """Search author, title of Article."""
    hidden = frozenset[str]()
    repo = ArticleRepository(session, **access.repo_kwargs)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[ArticleRead](
        items=[ArticleRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )


@router.get(
    "/collections/search",
    response_model=_service.SearchPage[CollectionRead],
)
async def search_collections(
    session: _db.SessionDep,
    q: _Q,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_collections["list"])],
    limit: _LIMIT = 20,
) -> _service.SearchPage[CollectionRead]:
    """Search handle, title of Collection."""
    hidden = frozenset[str]()
    repo = CollectionRepository(session, **access.repo_kwargs)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[CollectionRead](
        items=[CollectionRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )


@router.get(
    "/customers/search",
    response_model=_service.SearchPage[CustomerRead],
)
async def search_customers(
    session: _db.SessionDep,
    q: _Q,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_customers["list"])],
    limit: _LIMIT = 20,
) -> _service.SearchPage[CustomerRead]:
    """Search email, first_name, last_name, phone of Customer."""
    hidden = frozenset[str]()
    repo = CustomerRepository(session, **access.repo_kwargs)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[CustomerRead](
        items=[CustomerRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )


@router.get(
    "/discounts/search",
    response_model=_service.SearchPage[DiscountRead],
)
async def search_discounts(
    session: _db.SessionDep,
    q: _Q,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_discounts["list"])],
    limit: _LIMIT = 20,
) -> _service.SearchPage[DiscountRead]:
    """Search code, title of Discount."""
    hidden = frozenset[str]()
    repo = DiscountRepository(session, **access.repo_kwargs)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[DiscountRead](
        items=[DiscountRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )


@router.get(
    "/locations/search",
    response_model=_service.SearchPage[LocationRead],
)
async def search_locations(
    session: _db.SessionDep,
    q: _Q,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_locations["list"])],
    limit: _LIMIT = 20,
) -> _service.SearchPage[LocationRead]:
    """Search name of Location."""
    hidden = frozenset[str]()
    repo = LocationRepository(session, **access.repo_kwargs)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[LocationRead](
        items=[LocationRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )


@router.get(
    "/orders/search",
    response_model=_service.SearchPage[OrderRead],
)
async def search_orders(
    session: _db.SessionDep,
    q: _Q,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_orders["list"])],
    limit: _LIMIT = 20,
) -> _service.SearchPage[OrderRead]:
    """Search email, note of Order."""
    hidden = frozenset[str]()
    repo = OrderRepository(session, **access.repo_kwargs)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[OrderRead](
        items=[OrderRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )


@router.get(
    "/products/search",
    response_model=_service.SearchPage[ProductRead],
)
async def search_products(
    session: _db.SessionDep,
    q: _Q,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_products["list"])],
    limit: _LIMIT = 20,
) -> _service.SearchPage[ProductRead]:
    """Search handle, title, vendor of Product."""
    hidden = frozenset[str]()
    repo = ProductRepository(session, **access.repo_kwargs)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[ProductRead](
        items=[ProductRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )


@router.get(
    "/reviews/search",
    response_model=_service.SearchPage[ReviewRead],
)
async def search_reviews(
    session: _db.SessionDep,
    q: _Q,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_reviews["list"])],
    limit: _LIMIT = 20,
) -> _service.SearchPage[ReviewRead]:
    """Search body, title of Review."""
    hidden = frozenset[str]()
    repo = ReviewRepository(session, **access.repo_kwargs)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[ReviewRead](
        items=[ReviewRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )


@router.get(
    "/tags/search",
    response_model=_service.SearchPage[TagRead],
)
async def search_tags(
    session: _db.SessionDep,
    q: _Q,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_tags["list"])],
    limit: _LIMIT = 20,
) -> _service.SearchPage[TagRead]:
    """Search name of Tag."""
    hidden = frozenset[str]()
    repo = TagRepository(session, **access.repo_kwargs)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[TagRead](
        items=[TagRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )


@router.get(
    "/variants/search",
    response_model=_service.SearchPage[VariantRead],
)
async def search_variants(
    session: _db.SessionDep,
    q: _Q,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_variants["list"])],
    limit: _LIMIT = 20,
) -> _service.SearchPage[VariantRead]:
    """Search barcode, sku, title of Variant."""
    hidden = frozenset[str]()
    repo = VariantRepository(session, **access.repo_kwargs)
    rows, total = await _service.find(repo, q, limit, hidden)
    return _service.SearchPage[VariantRead](
        items=[VariantRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
    )
