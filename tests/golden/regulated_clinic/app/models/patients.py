"""SQLAlchemy model for Patient (generated)."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy import orm as _orm

from app.models import _base as _models_base
from app.regulated import fieldtype as _rg

if _t.TYPE_CHECKING:
    from app.models.appointments import Appointment


class Patient(_models_base.Base):
    __tablename__ = "patients"

    id: _orm.Mapped[_uuid.UUID] = _orm.mapped_column(_sa.Uuid(), primary_key=True, default=_uuid.uuid4)
    name: _orm.Mapped[str] = _orm.mapped_column(_rg.EncryptedText("patients", "name"), nullable=False)
    dob: _orm.Mapped[str | None] = _orm.mapped_column(_rg.EncryptedText("patients", "dob"), nullable=True)
    phone: _orm.Mapped[str | None] = _orm.mapped_column(_rg.EncryptedText("patients", "phone"), nullable=True)
    postcode: _orm.Mapped[str | None] = _orm.mapped_column(_sa.String(10), nullable=True)
    age: _orm.Mapped[int | None] = _orm.mapped_column(_sa.Integer(), nullable=True)
    notes: _orm.Mapped[str | None] = _orm.mapped_column(_sa.Text(), nullable=True)
    insurance_no: _orm.Mapped[str | None] = _orm.mapped_column(_rg.TokenisedText("patients", "insurance_no"), nullable=True)
    tenant_id: _orm.Mapped[_uuid.UUID | None] = _orm.mapped_column(
        _sa.ForeignKey("auth_tenants.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    created_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True), nullable=False, default=_models_base.utcnow
    )
    updated_at: _orm.Mapped[_dt.datetime] = _orm.mapped_column(
        _sa.DateTime(timezone=True),
        nullable=False,
        default=_models_base.utcnow,
        onupdate=_models_base.utcnow,
    )

    appointments: _orm.Mapped[list["Appointment"]] = _orm.relationship('Appointment', back_populates='patient', foreign_keys="[Appointment.patient_id]", passive_deletes=True)
