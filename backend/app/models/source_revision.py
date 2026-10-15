from sqlalchemy import Boolean, CheckConstraint, ForeignKeyConstraint, Integer, PrimaryKeyConstraint, Text, UniqueConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from typing import Any
from uuid import UUID as PyUUID

from app.models.base import Base


class SourceRevision(Base):
    __tablename__ = 'source_revisions'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='source_revisions_pkey'),
        UniqueConstraint('document_id', 'id', name='source_revisions_document_id_id_key'),
        ForeignKeyConstraint(['document_id'], ['documents.id'], name='source_revisions_document_id_fkey'),
        CheckConstraint("jsonb_typeof(limitations) = 'array'::text", name='source_revisions_limitations_check'),
        CheckConstraint("mode = ANY (ARRAY['complete'::text, 'skip_handwriting'::text])", name='source_revisions_mode_check'),
        CheckConstraint('page_count > 0', name='source_revisions_page_count_check'),
        CheckConstraint("status = ANY (ARRAY['staging'::text, 'published'::text, 'failed'::text, 'cancelled'::text])", name='source_revisions_status_check'),
    )

    id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    document_id: Mapped[PyUUID] = mapped_column(UUID)
    status: Mapped[str] = mapped_column(Text)
    upload_complete: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
    page_count: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(Text)
    skip_confirmed: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
    limitations: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=sql_text("'[]'::jsonb"))
