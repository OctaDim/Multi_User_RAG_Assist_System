from sqlalchemy import BigInteger, ForeignKeyConstraint, PrimaryKeyConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from typing import Any
from uuid import UUID as PyUUID

from app.models.base import Base


class DocumentPolicy(Base):
    __tablename__ = 'document_policies'
    __table_args__ = (
        PrimaryKeyConstraint('owner_id', name='document_policies_pkey'),
        ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='document_policies_owner_id_fkey'),
    )

    owner_id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    limits: Mapped[Any] = mapped_column(JSONB, nullable=False)
    permissions: Mapped[Any] = mapped_column(JSONB, nullable=False)
    handwriting_epoch: Mapped[int] = mapped_column(BigInteger, server_default=sql_text('0'))
