"""Audit B1-057: built-in auth generator (soft-delete tombstone, purge, samples, test coverage)."""

import ast
import json
from pathlib import Path

import pytest

from app.core.generator import generate
from app.core.generator.features.auth.module import _custom_field
from app.core.spec_models import Spec, SpecAuthCustomField

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _field(**kw: object) -> SpecAuthCustomField:
    base: dict[str, object] = {"name": "code", "label": "Code"}
    base.update(kw)
    return SpecAuthCustomField.model_validate(base)


def _eval(expr: str, n: int = 0) -> object:
    return eval(expr, {"n": n})  # noqa: S307 - generator-produced literal


def _tree(name: str) -> dict[str, str]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return generate(Spec.model_validate(data))


@pytest.fixture(scope="module")
def shop() -> dict[str, str]:
    return _tree("shop_auth.json")


@pytest.fixture(scope="module")
def tenant() -> dict[str, str]:
    return _tree("authz_tenant.json")


# F-0296 -------------------------------------------------------------------------------


def test_string_sample_respects_max_length() -> None:
    ctx = _custom_field(_field(type="string", max_length=3))
    for n in range(10):
        assert len(_eval(ctx.sample)) <= 3  # type: ignore[arg-type]
        assert len(_eval(ctx.variant, n)) <= 3  # type: ignore[arg-type]


def test_integer_sample_respects_max_value() -> None:
    ctx = _custom_field(_field(type="integer", max_value=0))
    assert _eval(ctx.sample) <= 0  # type: ignore[operator]
    unique = _custom_field(_field(type="integer", max_value=5, unique=True))
    values = {_eval(unique.variant, n) for n in range(10)}
    assert max(values) <= 5 and len(values) == 10  # type: ignore[type-var]


def test_float_sample_respects_max_value() -> None:
    ctx = _custom_field(_field(type="float", max_value=-5))
    assert _eval(ctx.sample) <= -5  # type: ignore[operator]


def test_bounded_integer_variant_stays_in_range() -> None:
    ctx = _custom_field(_field(type="integer", min_value=1, max_value=3, unique=True))
    assert {_eval(ctx.variant, n) for n in range(10)} <= {1, 2, 3}


def test_unique_enum_variants_differ() -> None:
    ctx = _custom_field(_field(type="enum", enum_values=["a", "b"], unique=True))
    assert _eval(ctx.variant, 0) != _eval(ctx.variant, 1)
    assert {_eval(ctx.variant, n) for n in range(10)} <= {"a", "b"}


# F-0293 -------------------------------------------------------------------------------


def test_soft_delete_frees_email_and_drops_credentials(shop: dict[str, str]) -> None:
    src = shop["app/auth/service.py"]
    body = src.split("async def delete_account", 1)[1].split("# --- tokens", 1)[0]
    assert "user.email = " in body and "@invalid" in body
    assert "user.phone = None" in body
    assert "user.password_hash = " in body
    assert "erase_emails" in body


# F-0294 -------------------------------------------------------------------------------


def test_hard_delete_docstring_does_not_overpromise() -> None:
    data = json.loads((FIXTURES / "shop_auth.json").read_text(encoding="utf-8"))
    data["auth"]["deletion_mode"] = "hard"
    router = generate(Spec.model_validate(data))["app/auth/router.py"]
    assert "everything that belongs to it" not in router
    assert "created_by_id" in router and "NULL" in router


# F-0295 -------------------------------------------------------------------------------


def test_purge_module_is_generated(shop: dict[str, str]) -> None:
    src = shop["app/auth/purge.py"]
    ast.parse(src)
    for name in ("AuthRefreshToken", "AuthVerificationCode", "AuthInvitation", "AuthSession"):
        assert name in src
    assert "async def purge_expired" in src and "__main__" in src


def test_purge_is_tested_in_generated_suite(shop: dict[str, str]) -> None:
    assert "purge_expired" in shop["tests/test_auth.py"]


# F-0297 / F-0298 / F-0299 -----------------------------------------------------------------


def test_invitation_reuse_test_can_fail(tenant: dict[str, str]) -> None:
    src = tenant["tests/test_invitations.py"]
    block = src.split("async def test_an_invitation_works_once", 1)[1].split("\nasync def ", 1)[0]
    assert "session_factory" in block and "delete" in block
    assert "in (400, 409)" not in block


def test_tenancy_tests_cover_update_and_replace(tenant: dict[str, str]) -> None:
    src = tenant["tests/test_tenancy.py"]
    assert "tenant_b.patch(" in src or "tenant_b.put(" in src


def test_builtin_jwt_tests_cover_header_tampering(shop: dict[str, str]) -> None:
    src = shop["tests/test_auth.py"]
    assert '"none"' in src and "kid" in src
