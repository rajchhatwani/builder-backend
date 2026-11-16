"""PATCH bodies: an explicit null is only allowed for columns that accept NULL."""

from typing import Any, ClassVar

from pydantic import BaseModel, model_validator


class NoNullPatch(BaseModel):
    """Set `not_null` to the field names whose DB column is NOT NULL; null on them gives a 422."""

    not_null: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_explicit_null(self) -> Any:
        bad = sorted(n for n in self.model_fields_set & self.not_null if getattr(self, n) is None)
        if bad:
            raise ValueError(f"{', '.join(bad)} cannot be null")
        return self
