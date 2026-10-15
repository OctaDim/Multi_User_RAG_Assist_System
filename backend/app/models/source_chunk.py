from pgvector.sqlalchemy import VECTOR
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint, Text, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from typing import Any
from uuid import UUID as PyUUID

from app.models.base import Base


class SourceChunk(Base):
    __tablename__ = 'source_chunks'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='source_chunks_pkey'),
        ForeignKeyConstraint(['revision_id', 'page'], ['source_pages.revision_id', 'source_pages.page'], name='source_chunks_revision_id_page_fkey'),
        CheckConstraint('span_end = (span_start + char_length(text))', name='source_chunks_check'),
        CheckConstraint("kind = ANY (ARRAY['printed'::text, 'handwritten'::text, 'skip'::text])", name='source_chunks_kind_check'),
        CheckConstraint('span_start >= 0', name='source_chunks_span_start_check'),
        Index('source_chunks_revision', 'revision_id'),
    )

    id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    revision_id: Mapped[PyUUID] = mapped_column(UUID)
    page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    span_start: Mapped[int] = mapped_column(Integer)
    span_end: Mapped[int] = mapped_column(Integer)
    coordinates: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=sql_text("'{}'::jsonb"))
    kind: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(384))
