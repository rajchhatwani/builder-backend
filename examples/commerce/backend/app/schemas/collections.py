"""Pydantic schemas for Collection (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import pydantic as _pd


class CollectionCreate(_pd.BaseModel):
    title: str = _pd.Field(max_length=200)
    handle: str = _pd.Field(max_length=200)
    description_html: str | None = _pd.Field(default=None)
    kind: _t.Literal['manual', 'smart'] | None = _pd.Field(default='manual')
    rules: _t.Any = _pd.Field(default=None)
    sort_order: _t.Literal['manual', 'best_selling', 'title_asc', 'title_desc', 'price_asc', 'price_desc', 'newest'] | None = _pd.Field(default='manual')
    published: bool | None = _pd.Field(default=False)
    published_at: _dt.datetime | None = _pd.Field(default=None)
    seo_title: str | None = _pd.Field(default=None, max_length=70)
    seo_description: str | None = _pd.Field(default=None, max_length=320)
    parent_id: _uuid.UUID | None = None
    products: list[_uuid.UUID] = _pd.Field(default_factory=list)


class CollectionUpdate(_pd.BaseModel):
    title: str | None = _pd.Field(default=None, max_length=200)
    handle: str | None = _pd.Field(default=None, max_length=200)
    description_html: str | None = _pd.Field(default=None)
    kind: _t.Literal['manual', 'smart'] | None = _pd.Field(default=None)
    rules: _t.Any = _pd.Field(default=None)
    sort_order: _t.Literal['manual', 'best_selling', 'title_asc', 'title_desc', 'price_asc', 'price_desc', 'newest'] | None = _pd.Field(default=None)
    published: bool | None = _pd.Field(default=None)
    published_at: _dt.datetime | None = _pd.Field(default=None)
    seo_title: str | None = _pd.Field(default=None, max_length=70)
    seo_description: str | None = _pd.Field(default=None, max_length=320)
    parent_id: _uuid.UUID | None = None
    products: list[_uuid.UUID] | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("title", "handle", "products"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class CollectionRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    title: str
    handle: str
    description_html: str | None
    kind: _t.Literal['manual', 'smart'] | None
    rules: _t.Any
    sort_order: _t.Literal['manual', 'best_selling', 'title_asc', 'title_desc', 'price_asc', 'price_desc', 'newest'] | None
    published: bool | None
    published_at: _dt.datetime | None
    seo_title: str | None
    seo_description: str | None
    parent_id: _uuid.UUID | None
    children: list[_uuid.UUID] = _pd.Field(default_factory=list)
    products: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("children", "products", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
