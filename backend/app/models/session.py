from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKeyConstraint, PrimaryKeyConstraint, Text, UniqueConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID as PyUUID

from app.models.base import Base


class Session(Base):
    __tablename__ = 'sessions'
    __table_args__ = (
        PrimaryKeyConstraint('token_hash', name='sessions_pkey'),
        UniqueConstraint('id', 'owner_id', name='session_identity'),
        ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='sessions_owner_id_fkey'),
    )

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_id: Mapped[PyUUID] = mapped_column(UUID)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
    id: Mapped[PyUUID] = mapped_column(UUID, server_default=sql_text('gen_random_uuid()'))
