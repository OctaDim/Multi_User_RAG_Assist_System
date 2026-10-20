from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKeyConstraint, PrimaryKeyConstraint, UniqueConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID as PyUUID

from app.models.base import Base


class Conversation(Base):
    __tablename__ = 'conversations'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='conversations_pkey'),
        UniqueConstraint('id', 'owner_id', name='conversations_id_owner_id_key'),
        ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='conversations_owner_id_fkey'),
    )

    id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    owner_id: Mapped[PyUUID] = mapped_column(UUID)
    context_epoch: Mapped[int] = mapped_column(BigInteger, server_default=sql_text('0'))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=sql_text('clock_timestamp()'))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=sql_text('clock_timestamp()'))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
