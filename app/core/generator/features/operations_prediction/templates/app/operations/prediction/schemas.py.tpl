"""Request and response models of the prediction API (generated). Values are strict integers."""

import datetime as dt
import typing as _t
import uuid

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

from app.operations.prediction import config as _config

LIMIT = 2**53  # JSON-exact in a browser, and sums of absolute errors cannot overflow


class PredictIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    subject_ref: str = Field(min_length=1, max_length=128)
    features: dict[str, StrictInt | StrictStr | StrictBool] = Field(default_factory=dict)

    @field_validator("features")
    @classmethod
    def _features(cls, value: dict[str, _t.Any]) -> dict[str, _t.Any]:
        if len(value) > _config.MAX_FEATURES:
            raise ValueError(f"at most {_config.MAX_FEATURES} features")
        for key, item in value.items():
            if not 1 <= len(key) <= 64:
                raise ValueError("a feature name is 1..64 characters")
            if isinstance(item, str) and len(item) > 256:
                raise ValueError("a text feature is at most 256 characters")
            if isinstance(item, int) and not isinstance(item, bool) and abs(item) > LIMIT:
                raise ValueError("an integer feature is within +-2**53")
        return value


class ActualIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual: StrictInt = Field(ge=-LIMIT, le=LIMIT)


class RecordOut(BaseModel):
    id: uuid.UUID
    kind: str
    subject_ref: str
    model_id: str
    unit: str
    value: int
    low: int
    high: int
    features: dict[str, _t.Any]
    actual: int | None
    actual_at: dt.datetime | None
    created_at: dt.datetime


class StatsOut(BaseModel):
    logged: int
    with_actual: int
    mae_milli: int | None
    abs_error_sum: int
    covered: int
    coverage_bp: int | None
