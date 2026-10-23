"""Pydantic schemas for Product (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class ProductCreate(_pd.BaseModel):
    title: str = _pd.Field(max_length=255)
    handle: str = _pd.Field(max_length=255)
    description_html: str | None = _pd.Field(default=None)
    vendor: str | None = _pd.Field(default=None, max_length=120)
    product_type: str | None = _pd.Field(default=None, max_length=120)
    status: _t.Literal['draft', 'active', 'archived'] = _pd.Field(default='draft')
    tags_cache: _t.Any = _pd.Field(default=None)
    options: _t.Any = _pd.Field(default=None)
    published_at: _dt.datetime | None = _pd.Field(default=None)
    seo_title: str | None = _pd.Field(default=None, max_length=70)
    seo_description: str | None = _pd.Field(default=None, max_length=320)
    requires_shipping: bool | None = _pd.Field(default=True)
    taxable: bool | None = _pd.Field(default=True)
    collections: list[_uuid.UUID] = _pd.Field(default_factory=list)
    tags: list[_uuid.UUID] = _pd.Field(default_factory=list)


class ProductUpdate(_pd.BaseModel):
    title: str | None = _pd.Field(default=None, max_length=255)
    handle: str | None = _pd.Field(default=None, max_length=255)
    description_html: str | None = _pd.Field(default=None)
    vendor: str | None = _pd.Field(default=None, max_length=120)
    product_type: str | None = _pd.Field(default=None, max_length=120)
    status: _t.Literal['draft', 'active', 'archived'] | None = _pd.Field(default=None)
    tags_cache: _t.Any = _pd.Field(default=None)
    options: _t.Any = _pd.Field(default=None)
    published_at: _dt.datetime | None = _pd.Field(default=None)
    seo_title: str | None = _pd.Field(default=None, max_length=70)
    seo_description: str | None = _pd.Field(default=None, max_length=320)
    requires_shipping: bool | None = _pd.Field(default=None)
    taxable: bool | None = _pd.Field(default=None)
    collections: list[_uuid.UUID] | None = None
    tags: list[_uuid.UUID] | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("title", "handle", "status", "collections", "tags"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ProductRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    title: str
    handle: str
    description_html: str | None
    vendor: str | None
    product_type: str | None
    status: _t.Literal['draft', 'active', 'archived']
    tags_cache: _t.Any
    options: _t.Any
    published_at: _dt.datetime | None
    seo_title: str | None
    seo_description: str | None
    requires_shipping: bool | None
    taxable: bool | None
    collections: list[_uuid.UUID] = _pd.Field(default_factory=list)
    images: list[_uuid.UUID] = _pd.Field(default_factory=list)
    reviews: list[_uuid.UUID] = _pd.Field(default_factory=list)
    tags: list[_uuid.UUID] = _pd.Field(default_factory=list)
    variants: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("collections", "images", "reviews", "tags", "variants", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
