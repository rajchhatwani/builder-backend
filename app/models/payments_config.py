import uuid
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import PaymentProvider
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectPaymentsConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Payments settings of one project (1:1 with projects).

    Kept when payments are switched off, so turning them on again restores everything.
    No provider secret is ever stored here: API keys and webhook secrets are environment
    variables of the generated project. The nested blocks mirror the spec models
    (SpecPaymentsPayable / Roles / Scale / Security) and are validated through them.
    """

    __tablename__ = "project_payments_configs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider: Mapped[PaymentProvider] = mapped_column(
        SAEnum(PaymentProvider, name="payment_provider", native_enum=False, length=12),
        nullable=False,
        default=PaymentProvider.stripe,
    )
    payable: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    currencies: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    max_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=10_000_000)
    success_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cancel_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    roles: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    refund_approval_threshold_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    scale: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    security: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
