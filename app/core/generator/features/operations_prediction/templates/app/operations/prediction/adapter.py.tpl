"""The predictor adapter (generated): an interface plus the deterministic FAKE model. A real model is a class with the
same `predict` method registered in PREDICTORS (a custom extension); nothing here makes a network call.

Fake rule: value = sum of the integer features + the length of the string features + 1 per true flag + a stable
offset 0..99 taken from a hash of (kind, subject_ref, features); interval = value +- max(1, |value| * interval_bp / 10000)."""

import hashlib
import json
import typing as _t
from dataclasses import dataclass

Feature = int | str | bool


@dataclass(frozen=True)
class Prediction:
    value: int
    low: int
    high: int
    model_id: str


class Predictor(_t.Protocol):
    model_id: str

    def predict(self, kind: str, subject_ref: str, features: _t.Mapping[str, Feature]) -> Prediction: ...


class FakePredictor:
    def __init__(self, model_id: str, interval_bp: int) -> None:
        self.model_id = model_id
        self._interval_bp = interval_bp

    def predict(self, kind: str, subject_ref: str, features: _t.Mapping[str, Feature]) -> Prediction:
        total = 0
        for value in features.values():
            if isinstance(value, bool):
                total += 1 if value else 0
            elif isinstance(value, int):
                total += value
            else:
                total += len(value)
        digest = hashlib.sha256(json.dumps([kind, subject_ref, sorted(features.items())], separators=(",", ":"), default=str).encode()).digest()
        value = total + int.from_bytes(digest[:4], "big") % 100
        half = max(1, abs(value) * self._interval_bp // 10_000)
        return Prediction(value, value - half, value + half, self.model_id)


def error_rate_bp(numerator: int, denominator: int) -> int:
    """numerator * 10000 / denominator rounded half to even (integers)."""
    return divide_half_even(numerator * 10_000, denominator)


def divide_half_even(numerator: int, denominator: int) -> int:
    quotient, remainder = divmod(numerator, denominator)
    if 2 * remainder > denominator or (2 * remainder == denominator and quotient % 2 == 1):
        quotient += 1
    return quotient
