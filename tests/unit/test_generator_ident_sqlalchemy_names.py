"""F-0848: shortened constraint/index names must equal what SQLAlchemy derives in the models."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.generator.context import _ident

def _generated_convention() -> dict[str, str]:
    """The convention the generated models really use (read from the generated _base.py)."""
    from app.core.generator import generate
    from app.core.spec_models import Spec
    from tests.unit.test_generator import FIXTURES

    spec = Spec.model_validate_json((FIXTURES / "library.json").read_text(encoding="utf-8"))
    ns: dict = {}
    exec(generate(spec)["app/models/_base.py"], ns)  # noqa: S102
    return ns["NAMING_CONVENTION"]


_NC = _generated_convention()


def test_long_names_match_sqlalchemy_truncation() -> None:
    table = "customer_organization_membership_records"
    m = sa.MetaData(naming_convention=_NC)
    t = sa.Table(
        table,
        m,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("external_reference_identifier_code", sa.String(20), unique=True),
        sa.Column("another_long_indexed_field_name_here", sa.String(20), index=True),
    )
    d = postgresql.dialect()
    ddl = str(CreateTable(t).compile(dialect=d)) + "".join(str(CreateIndex(i).compile(dialect=d)) for i in t.indexes)
    assert _ident(f"uq_{table}_external_reference_identifier_code") in ddl
    assert _ident(f"ix_{table}_another_long_indexed_field_name_here") in ddl
    assert _ident(f"pk_{table}") in ddl
