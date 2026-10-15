from datetime import datetime
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint, Index, PrimaryKeyConstraint, Text, UniqueConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from typing import Any
from uuid import UUID as PyUUID

from app.models.base import Base


class Request(Base):
    __tablename__ = 'requests'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='requests_pkey'),
        UniqueConstraint('id', 'conversation_id', name='requests_id_conversation_id_key'),
        UniqueConstraint('owner_id', 'operation_key', name='requests_owner_id_operation_key_key'),
        ForeignKeyConstraint(['origin_session', 'owner_id'], ['sessions.id', 'sessions.owner_id'], name='request_session_owner'),
        ForeignKeyConstraint(['conversation_id', 'owner_id'], ['conversations.id', 'conversations.owner_id'], name='requests_conversation_id_owner_id_fkey'),
        ForeignKeyConstraint(['origin_tab', 'owner_id'], ['tabs.id', 'tabs.owner_id'], name='requests_origin_tab_owner_id_fkey'),
        CheckConstraint("state = ANY (ARRAY['accepted'::text, 'searching'::text, 'queued'::text, 'generating'::text, 'completed'::text, 'interrupted'::text, 'failed'::text])", name='requests_state_check'),
        CheckConstraint("origin_session IS NOT NULL OR (state = ANY (ARRAY['completed'::text, 'interrupted'::text, 'failed'::text]))", name='unfinished_session_required'),
        Index('one_unfinished_request', 'conversation_id', unique=True, postgresql_where=sql_text("(state = ANY (ARRAY['accepted'::text, 'searching'::text, 'queued'::text, 'generating'::text]))")),
        Index('requests_conversation_order', 'conversation_id', 'created_at', 'id'),
    )

    id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    conversation_id: Mapped[PyUUID] = mapped_column(UUID)
    owner_id: Mapped[PyUUID] = mapped_column(UUID)
    operation_key: Mapped[PyUUID] = mapped_column(UUID)
    fingerprint: Mapped[str] = mapped_column(Text)
    scope: Mapped[list[PyUUID]] = mapped_column(ARRAY(UUID))
    origin_tab: Mapped[PyUUID] = mapped_column(UUID)
    state: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    execution_epoch: Mapped[int] = mapped_column(BigInteger)
    context_epoch: Mapped[int] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(BigInteger, server_default=sql_text('1'))
    answer_text: Mapped[str] = mapped_column(Text, server_default=sql_text("''::text"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text('now()'))
    passport: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=sql_text("'{}'::jsonb"))
    origin_session: Mapped[PyUUID | None] = mapped_column(UUID)
