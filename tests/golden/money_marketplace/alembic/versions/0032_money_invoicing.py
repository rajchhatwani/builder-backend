"""money pack: invoicing and payouts

Revision ID: 0032
Revises: 0031
Create Date: rendered from the spec by Backend Builder

Invoice counters (gapless numbers), invoices, lines, payments, payouts. Guards in the database: an invoice that is
not a draft keeps its content (only status, paid amount and the void markers change), paid and void invoices
are frozen, lines of a non-draft invoice cannot change. No TRUNCATE trigger.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INVOICE_GUARD = """
CREATE FUNCTION invoices_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('paid', 'void') THEN
        RAISE EXCEPTION 'invoice % is % and cannot change', OLD.id, OLD.status USING ERRCODE = '23514';
    END IF;
    IF OLD.status <> 'draft' AND (
        NEW.kind <> OLD.kind OR NEW.number IS DISTINCT FROM OLD.number OR NEW.counterparty <> OLD.counterparty
        OR NEW.counterparty_ref IS DISTINCT FROM OLD.counterparty_ref OR NEW.currency <> OLD.currency
        OR NEW.issue_date IS DISTINCT FROM OLD.issue_date OR NEW.due_date IS DISTINCT FROM OLD.due_date
        OR NEW.notes IS DISTINCT FROM OLD.notes OR NEW.subtotal_minor <> OLD.subtotal_minor
        OR NEW.tax_minor <> OLD.tax_minor OR NEW.total_minor <> OLD.total_minor
        OR NEW.issue_tx_id IS DISTINCT FROM OLD.issue_tx_id OR NEW.tenant_id <> OLD.tenant_id
    ) THEN
        RAISE EXCEPTION 'invoice % is issued: its content is immutable', OLD.id USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$
"""

_LINE_GUARD = """
CREATE FUNCTION invoice_lines_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    inv uuid;
    inv_status text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        inv := OLD.invoice_id;
    ELSE
        inv := NEW.invoice_id;
    END IF;
    SELECT status INTO inv_status FROM invoices WHERE id = inv;
    IF inv_status IS NOT NULL AND inv_status <> 'draft' THEN
        RAISE EXCEPTION 'invoice % is issued: its lines are immutable', inv USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "invoice_counters",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("last_value", sa.BigInteger(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_invoice_counters_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "kind", name="uq_invoice_counters_kind"),
    )
    op.create_index(op.f("ix_invoice_counters_tenant_id"), "invoice_counters", ["tenant_id"], unique=False)

    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("number", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("counterparty", sa.String(length=200), nullable=False),
        sa.Column("counterparty_ref", sa.String(length=64), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("subtotal_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("paid_minor", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("issue_tx_id", sa.Uuid(), nullable=True),
        sa.Column("void_tx_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('receivable', 'payable')", name="ck_invoices_kind"),
        sa.CheckConstraint("paid_minor >= 0 AND paid_minor <= total_minor", name="ck_invoices_paid_range"),
        sa.CheckConstraint("status IN ('draft', 'issued', 'partially_paid', 'paid', 'void')", name="ck_invoices_status"),
        sa.CheckConstraint("total_minor = subtotal_minor + tax_minor", name="ck_invoices_total_sum"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_invoices_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_invoices_number"),
    )
    op.create_index(op.f("ix_invoices_tenant_id"), "invoices", ["tenant_id"], unique=False)

    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_rate", sa.String(length=32), nullable=True),
        sa.Column("net_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_minor", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("quantity >= 1 AND unit_price_minor >= 0", name="ck_invoice_lines_positive"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name="fk_invoice_lines_invoice_id_invoices"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_invoice_lines_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_id", "line_no", name="uq_invoice_lines_invoice_id_line_no"),
    )
    op.create_index(op.f("ix_invoice_lines_tenant_id"), "invoice_lines", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_invoice_lines_invoice_id"), "invoice_lines", ["invoice_id"], unique=False)

    op.create_table(
        "invoice_payments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(length=128), nullable=True),
        sa.Column("ledger_tx_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="ck_invoice_payments_positive"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name="fk_invoice_payments_invoice_id_invoices"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_invoice_payments_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_invoice_payments_idempotency_key"),
    )
    op.create_index(op.f("ix_invoice_payments_tenant_id"), "invoice_payments", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_invoice_payments_invoice_id"), "invoice_payments", ["invoice_id"], unique=False)

    op.create_table(
        "money_payouts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("seller", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("gross_minor", sa.BigInteger(), nullable=False),
        sa.Column("commission_bp", sa.Integer(), nullable=False),
        sa.Column("commission_minor", sa.BigInteger(), nullable=False),
        sa.Column("seller_minor", sa.BigInteger(), nullable=False),
        sa.Column("split_tx_id", sa.Uuid(), nullable=False),
        sa.Column("payout_tx_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "commission_minor >= 0 AND seller_minor >= 0 AND gross_minor = commission_minor + seller_minor",
            name="ck_money_payouts_split",
        ),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name="fk_money_payouts_invoice_id_invoices"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], name="fk_money_payouts_tenant_id_auth_tenants", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_money_payouts_idempotency_key"),
        sa.UniqueConstraint("invoice_id", name="uq_money_payouts_invoice_id"),
    )
    op.create_index(op.f("ix_money_payouts_tenant_id"), "money_payouts", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_money_payouts_seller"), "money_payouts", ["seller"], unique=False)

    op.execute(_INVOICE_GUARD)
    op.execute("CREATE TRIGGER invoices_guard BEFORE UPDATE ON invoices FOR EACH ROW EXECUTE FUNCTION invoices_guard()")
    op.execute(_LINE_GUARD)
    op.execute(
        "CREATE TRIGGER invoice_lines_guard BEFORE INSERT OR UPDATE OR DELETE ON invoice_lines "
        "FOR EACH ROW EXECUTE FUNCTION invoice_lines_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER invoice_lines_guard ON invoice_lines")
    op.execute("DROP FUNCTION invoice_lines_guard()")
    op.execute("DROP TRIGGER invoices_guard ON invoices")
    op.execute("DROP FUNCTION invoices_guard()")
    op.drop_table("money_payouts")
    op.drop_table("invoice_payments")
    op.drop_table("invoice_lines")
    op.drop_table("invoices")
    op.drop_table("invoice_counters")
