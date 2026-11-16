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
    with pytest.raises(ValidationError):
        ProjectRoleCreate(name="admin\n")


def test_custom_field_name_rejects_trailing_newline() -> None:
    with pytest.raises(ValidationError):
        AuthCustomFieldCreate(name="plan\n", field_type="string")


def test_valid_values_still_accepted() -> None:
    assert OrganizationCreate(name="x", slug="acme-1").slug == "acme-1"
