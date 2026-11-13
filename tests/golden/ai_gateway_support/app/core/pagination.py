from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


def page_params(default_limit: int, max_limit: int) -> Callable[..., PageParams]:
    """Dependency factory: each entity picks its own default and maximum page size."""

    def dependency(
        limit: Annotated[int, Query(ge=1, le=max_limit)] = default_limit,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> PageParams:
        return PageParams(limit=limit, offset=offset)

    return dependency
