from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKeyConstraint, Identity, PrimaryKeyConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from typing import Any
from uuid import UUID as PyUUID

from app.models.base import Base


class DocumentPolicyAudit(Base):
    __tablename__ = 'document_policy_audit'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='document_policy_audit_pkey'),
        ForeignKeyConstraint(['actor_id'], ['accounts.id'], name='document_policy_audit_actor_id_fkey'),
        ForeignKeyConstraint(['target_id'], ['accounts.id'], name='document_policy_audit_target_id_fkey'),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    actor_id: Mapped[PyUUID] = mapped_column(UUID)
    target_id: Mapped[PyUUID] = mapped_column(UUID)
    previous: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated: Mapped[Any] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text('clock_timestamp()'))
