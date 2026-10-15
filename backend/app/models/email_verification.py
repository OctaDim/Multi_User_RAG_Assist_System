from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKeyConstraint, PrimaryKeyConstraint, Text, text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID as PyUUID

from app.models.base import Base


class EmailVerification(Base):
    __tablename__ = 'email_verifications'
    __table_args__ = (
        PrimaryKeyConstraint('token_hash', name='email_verifications_pkey'),
        ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='email_verifications_owner_id_fkey'),
    )

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_id: Mapped[PyUUID] = mapped_column(UUID)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
