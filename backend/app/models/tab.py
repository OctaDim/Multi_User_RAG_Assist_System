from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKeyConstraint, Index, PrimaryKeyConstraint, Text, UniqueConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID as PyUUID

from app.models.base import Base


class Tab(Base):
    __tablename__ = 'tabs'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='tabs_pkey'),
        UniqueConstraint('id', 'owner_id', name='tabs_id_owner_id_key'),
        ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='tabs_owner_id_fkey'),
        Index('tabs_presence_due', 'ack_until', 'deadline'),
    )

    id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    owner_id: Mapped[PyUUID] = mapped_column(UUID)
    proof_hash: Mapped[str] = mapped_column(Text)
    connection_epoch: Mapped[int] = mapped_column(BigInteger, server_default=sql_text('0'))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
    confirmed: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
    ack_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    challenge_hash: Mapped[str | None] = mapped_column(Text)
