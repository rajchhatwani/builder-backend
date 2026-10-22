"""Pydantic schemas for Book (generated)."""
import datetime as _dt
import decimal as _decimal
import typing as _t
import uuid as _uuid

import pydantic as _pd


class BookCreate(_pd.BaseModel):
    title: str = _pd.Field(max_length=200)
    isbn: str | None = _pd.Field(default=None, max_length=20)
    pages: int = _pd.Field(default=100, ge=1)
    price: _decimal.Decimal | None = _pd.Field(default=_decimal.Decimal('9.99'), ge=0)
    status: _t.Literal['draft', 'published', 'archived'] = _pd.Field(default='draft')
    published_at: _dt.datetime | None = _pd.Field(default=None)
    in_stock: bool = _pd.Field(default=True)
    extra: _t.Any = _pd.Field(default_factory=lambda: {'tags': []})
    catalog_id: _uuid.UUID | None = _pd.Field(default=None)
    author_id: _uuid.UUID
    shelf_id: _uuid.UUID | None = None
    borrowers: list[_uuid.UUID] = _pd.Field(default_factory=list)


class BookUpdate(_pd.BaseModel):
    title: str | None = _pd.Field(default=None, max_length=200)
    isbn: str | None = _pd.Field(default=None, max_length=20)
    pages: int | None = _pd.Field(default=None, ge=1)
    price: _decimal.Decimal | None = _pd.Field(default=None, ge=0)
    status: _t.Literal['draft', 'published', 'archived'] | None = _pd.Field(default=None)
    published_at: _dt.datetime | None = _pd.Field(default=None)
    in_stock: bool | None = _pd.Field(default=None)
    extra: _t.Any = _pd.Field(default=None)
    catalog_id: _uuid.UUID | None = _pd.Field(default=None)
    author_id: _uuid.UUID | None = None
    shelf_id: _uuid.UUID | None = None
    borrowers: list[_uuid.UUID] | None = None

    @_pd.model_validator(mode="after")
    def reject_null_values(self) -> _t.Self:
        for name in ("title", "pages", "status", "in_stock", "author_id", "borrowers"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class BookRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    title: str
    isbn: str | None
    pages: int
    price: _decimal.Decimal | None
    status: _t.Literal['draft', 'published', 'archived']
    published_at: _dt.datetime | None
    in_stock: bool
    extra: _t.Any
    catalog_id: _uuid.UUID | None
    author_id: _uuid.UUID
    shelf_id: _uuid.UUID | None
    borrowers: list[_uuid.UUID] = _pd.Field(default_factory=list)
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @_pd.field_validator("borrowers", mode="before")
    @classmethod
    def coerce_collection_ids(cls, value: _t.Any) -> _t.Any:
        return [item.id for item in value]
