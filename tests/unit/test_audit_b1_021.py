"""Audit B1-021: schema bounds (F-0216 rate limits, F-0217/18 nulls, F-0219 int bounds)."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.core import validation_documents as vd
from app.core.validation import _RATE_LIMIT_RE
from app.schemas.ai_registry import AiSettingsWrite
from app.schemas.auth_config import AuthConfigUpdate
from app.schemas.auth_custom_field import AuthCustomFieldUpdate
from app.schemas.entity import EntityUpdate
from app.schemas.field import FieldCreate, FieldUpdate
from app.schemas.project import ProjectUpdate
from app.schemas.project_role import ProjectRoleUpdate
from app.schemas.relation import RelationUpdate


@pytest.mark.parametrize("bad", ["5/0minutes", "0/hour", "05/hour", "5/00minute", "0/0hour"])
def test_rate_limit_zero_count_or_window_is_refused(bad: str) -> None:
    assert _RATE_LIMIT_RE.fullmatch(bad) is None
    assert vd.RATE_RE.fullmatch(bad) is None
    with pytest.raises(ValidationError):
        AuthConfigUpdate(login_rate_limit=bad)


@pytest.mark.parametrize("good", ["5/minute", "10/hour", "5/15minutes", "100/day"])
def test_rate_limit_valid_forms_still_pass(good: str) -> None:
    assert _RATE_LIMIT_RE.fullmatch(good)
    assert vd.RATE_RE.fullmatch(good)
    AuthConfigUpdate(login_rate_limit=good)


@pytest.mark.parametrize(
    ("schema", "key"),
    [
        (AuthConfigUpdate, "enabled"),
        (AuthConfigUpdate, "access_token_ttl_minutes"),
        (AuthConfigUpdate, "login_rate_limit"),
        (AuthConfigUpdate, "jwt_algorithm"),
        (EntityUpdate, "name"),
        (EntityUpdate, "options"),
        (FieldUpdate, "type"),
        (FieldUpdate, "name"),
        (ProjectRoleUpdate, "label"),
        (AuthCustomFieldUpdate, "label"),
        (RelationUpdate, "on_delete"),
        (ProjectUpdate, "name"),
    ],
)
def test_patch_null_on_not_null_column_is_422(schema: Any, key: str) -> None:
    body: dict[str, Any] = {key: None}
    if schema is ProjectUpdate:
        body["version"] = 1
    with pytest.raises(ValidationError):
        schema.model_validate(body)


def test_patch_null_on_nullable_column_and_omitted_keys_still_pass() -> None:
    assert AuthConfigUpdate.model_validate({"smtp_config": None}).smtp_config is None
    assert EntityUpdate.model_validate({}).name is None
    assert FieldUpdate.model_validate({"max_length": None}).max_length is None


def test_int_columns_are_bounded() -> None:
    with pytest.raises(ValidationError):
        FieldUpdate(position=2**31)
    with pytest.raises(ValidationError):
        FieldUpdate(max_length=3_000_000_000)
    with pytest.raises(ValidationError):
        FieldCreate(name="a", type="string", position=2**31)
    with pytest.raises(ValidationError):
        ProjectRoleUpdate(position=2**31)
    with pytest.raises(ValidationError):
        AuthCustomFieldUpdate(position=2**31)
    with pytest.raises(ValidationError):
        AiSettingsWrite(monthly_budget_micro_usd=2**70)
    assert FieldUpdate(position=2**31 - 1).position == 2**31 - 1
