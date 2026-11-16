"""Audit F-0222: slug/name validators must reject a trailing newline."""

import pytest
from pydantic import ValidationError

from app.schemas.auth_custom_field import AuthCustomFieldCreate
from app.schemas.organization import OrganizationCreate
from app.schemas.project import ProjectCreate
from app.schemas.project_role import ProjectRoleCreate


def test_org_slug_rejects_trailing_newline() -> None:
    with pytest.raises(ValidationError):
        OrganizationCreate(name="x", slug="acme\n")


def test_project_slug_rejects_trailing_newline() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(name="x", slug="acme\n")


def test_role_name_rejects_trailing_newline() -> None:
    with pytest.raises(ValidationError) as ei:
        ProjectRoleCreate(name="admin\n", label="x")
    assert {e["loc"] for e in ei.value.errors()} == {("name",)}


def test_custom_field_name_rejects_trailing_newline() -> None:
    with pytest.raises(ValidationError) as ei:
        AuthCustomFieldCreate(name="plan\n", label="x", type="string")
    assert {e["loc"] for e in ei.value.errors()} == {("name",)}


def test_valid_values_still_accepted() -> None:
    assert OrganizationCreate(name="x", slug="acme-1").slug == "acme-1"
