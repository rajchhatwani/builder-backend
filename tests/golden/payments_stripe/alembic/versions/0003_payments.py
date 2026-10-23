"""payments tables

Revision ID: 0003
Revises: 0002
Create Date: rendered from the spec by Backend Builder

Payment, refund, dispute, webhook-event, idempotency, job, audit and mode-lock tables. The audit
table is protected by triggers: rows cannot be updated, the table cannot be truncated, and rows
cannot be deleted before they are 2555 days old (and then only by the purge tool).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "pay_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(12), nullable=False),
        sa.Column("livemode", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payable_id", sa.Uuid(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("refunded_minor", sa.BigInteger(), nullable=False),
        sa.Column("refund_reserved_minor", sa.BigInteger(), nullable=False),
        sa.Column("provider_session_id", sa.String(255), nullable=True),
        sa.Column("provider_payment_intent_id", sa.String(255), nullable=True),
        sa.Column("checkout_url", sa.Text(), nullable=True),
        sa.Column("success_url", sa.String(2000), nullable=False),
        sa.Column("cancel_url", sa.String(2000), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_pay_payments"),
        sa.UniqueConstraint("provider_session_id", name="uq_pay_payments_provider_session_id"),
        sa.CheckConstraint("amount_minor > 0", name="ck_pay_payments_amount_positive"),
        sa.CheckConstraint(
            "refunded_minor >= 0 AND refunded_minor <= refund_reserved_minor "
            "AND refund_reserved_minor <= amount_minor",
            name="ck_pay_payments_refund_bounds",
        ),
    )
    op.create_index(
        "ix_pay_payments_provider_payment_intent_id",
        "pay_payments",
        ["provider_payment_intent_id"],
    )
    op.create_index("ix_pay_payments_tenant_created", "pay_payments", ["tenant_id", "created_at"])
    op.create_index(
        "ix_pay_payments_creator_created", "pay_payments", ["created_by_id", "created_at"]
    )
    op.create_index("ix_pay_payments_status_updated", "pay_payments", ["status", "updated_at"])
    # One live payment per item: this is what stops the same order being charged twice.
    op.create_index(
        "uq_pay_payments_active_payable",
        "pay_payments",
        ["payable_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('creating', 'requires_payment', 'processing', 'succeeded')"
        ),
    )

    op.create_table(
        "pay_refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_refund_id", sa.String(255), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_pay_refunds"),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["pay_payments.id"],
            name="fk_pay_refunds_payment_id_pay_payments",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("provider_refund_id", name="uq_pay_refunds_provider_refund_id"),
        sa.CheckConstraint("amount_minor > 0", name="ck_pay_refunds_amount_positive"),
        sa.CheckConstraint(
            "approved_by_id IS NULL OR requested_by_id IS NULL OR approved_by_id <> requested_by_id",
            name="ck_pay_refunds_two_people",
        ),
    )
    op.create_index("ix_pay_refunds_payment_id", "pay_refunds", ["payment_id"])
    op.create_index("ix_pay_refunds_status_updated", "pay_refunds", ["status", "updated_at"])

    op.create_table(
        "pay_disputes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("provider_dispute_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("evidence_due_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_pay_disputes"),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["pay_payments.id"],
            name="fk_pay_disputes_payment_id_pay_payments",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("provider_dispute_id", name="uq_pay_disputes_provider_dispute_id"),
    )
    op.create_index("ix_pay_disputes_payment_id", "pay_disputes", ["payment_id"])

    op.create_table(
        "pay_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(12), nullable=False),
        sa.Column("event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("livemode", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_pay_webhook_events"),
        sa.UniqueConstraint("provider", "event_id", name="uq_pay_webhook_events_provider_event"),
    )
    op.create_index(
        "ix_pay_webhook_events_status_received", "pay_webhook_events", ["status", "received_at"]
    )

    op.create_table(
        "pay_idempotency_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(16), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pay_idempotency_keys"),
        sa.UniqueConstraint("scope_hash", name="uq_pay_idempotency_keys_scope_hash"),
    )
    op.create_index("ix_pay_idempotency_keys_expires_at", "pay_idempotency_keys", ["expires_at"])

    op.create_table(
        "pay_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(80), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedupe_key", sa.String(120), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_pay_jobs"),
        sa.UniqueConstraint("dedupe_key", name="uq_pay_jobs_dedupe_key"),
    )
    op.create_index("ix_pay_jobs_status_run_at", "pay_jobs", ["status", "run_at"])

    op.create_table(
        "pay_audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chain_key", sa.String(64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(10), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("event", sa.String(48), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pay_audit_log"),
        sa.UniqueConstraint("chain_key", "seq", name="uq_pay_audit_log_chain_seq"),
    )
    op.create_index("ix_pay_audit_log_chain_key", "pay_audit_log", ["chain_key"])

    op.create_table(
        "pay_lock",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(12), nullable=False),
        sa.Column("livemode", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pay_lock"),
    )

    op.execute(
        """
        CREATE FUNCTION pay_audit_protect() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF current_setting('payments.allow_audit_purge', true) = 'on'
                   AND OLD.at < now() - make_interval(days => 2555) THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'pay_audit_log rows cannot be deleted before the retention period';
            END IF;
            RAISE EXCEPTION 'pay_audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER pay_audit_append_only BEFORE UPDATE OR DELETE ON pay_audit_log "
        "FOR EACH ROW EXECUTE FUNCTION pay_audit_protect()"
    )
    op.execute(
        "CREATE TRIGGER pay_audit_no_truncate BEFORE TRUNCATE ON pay_audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION pay_audit_protect()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS pay_audit_no_truncate ON pay_audit_log")
    op.execute("DROP TRIGGER IF EXISTS pay_audit_append_only ON pay_audit_log")
    op.execute("DROP FUNCTION IF EXISTS pay_audit_protect()")
    op.drop_table("pay_lock")
    op.drop_table("pay_audit_log")
    op.drop_table("pay_jobs")
    op.drop_table("pay_idempotency_keys")
    op.drop_table("pay_webhook_events")
    op.drop_table("pay_disputes")
    op.drop_table("pay_refunds")
    op.drop_table("pay_payments")
