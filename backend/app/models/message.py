from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKeyConstraint, Identity, Index, PrimaryKeyConstraint, Text, UniqueConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from typing import Any
from uuid import UUID as PyUUID

from app.models.base import Base


class Message(Base):
    __tablename__ = 'messages'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='messages_pkey'),
        UniqueConstraint('request_id', 'role', name='messages_request_id_role_key'),
        ForeignKeyConstraint(['request_id', 'conversation_id'], ['requests.id', 'requests.conversation_id'], name='messages_request_id_conversation_id_fkey'),
        CheckConstraint("role = ANY (ARRAY['user'::text, 'assistant'::text])", name='messages_role_check'),
        Index('messages_conversation_order', 'conversation_id', 'id'),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    request_id: Mapped[PyUUID] = mapped_column(UUID)
    conversation_id: Mapped[PyUUID] = mapped_column(UUID)
    role: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    excluded: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
    source_flags: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=sql_text("'{}'::jsonb"))
