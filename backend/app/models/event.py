from sqlalchemy import BigInteger, ForeignKeyConstraint, Identity, Index, PrimaryKeyConstraint, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from typing import Any
from uuid import UUID as PyUUID

from app.models.base import Base


class Event(Base):
    __tablename__ = 'events'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='events_pkey'),
        ForeignKeyConstraint(['request_id', 'conversation_id'], ['requests.id', 'requests.conversation_id'], name='events_request_id_conversation_id_fkey'),
        Index('events_conversation_cursor', 'conversation_id', 'id'),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    request_id: Mapped[PyUUID] = mapped_column(UUID)
    conversation_id: Mapped[PyUUID] = mapped_column(UUID)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
