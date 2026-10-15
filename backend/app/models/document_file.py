from datetime import datetime
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint, Text, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from typing import Any
from uuid import UUID as PyUUID

from app.models.base import Base


class DocumentFile(Base):
    __tablename__ = 'document_files'
    __table_args__ = (
        PrimaryKeyConstraint('document_id', name='document_files_pkey'),
        ForeignKeyConstraint(['correction_base'], ['source_revisions.id'], name='document_files_correction_base_fkey'),
        ForeignKeyConstraint(['document_id'], ['documents.id'], name='document_files_document_id_fkey'),
        CheckConstraint('declared_bytes > 0', name='document_files_declared_bytes_check'),
        CheckConstraint("format = ANY (ARRAY['pdf'::text, 'docx'::text, 'txt'::text, 'md'::text])", name='document_files_format_check'),
        CheckConstraint("mode = ANY (ARRAY['complete'::text, 'skip_handwriting'::text])", name='document_files_mode_check'),
        CheckConstraint("state = ANY (ARRAY['receiving'::text, 'queued'::text, 'processing'::text, 'awaiting_choice'::text, 'ready'::text, 'failed'::text, 'cancelled'::text])", name='document_files_state_check'),
        Index('document_files_jobs', 'state', 'created_at'),
    )

    document_id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    batch_id: Mapped[PyUUID] = mapped_column(UUID)
    name: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(Text)
    declared_bytes: Mapped[int] = mapped_column(BigInteger)
    original_sha256: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    admitted_limits: Mapped[Any] = mapped_column(JSONB, nullable=False)
    admitted_handwriting_epoch: Mapped[int] = mapped_column(BigInteger, server_default=sql_text('0'))
    mode: Mapped[str] = mapped_column(Text, server_default=sql_text("'complete'::text"))
    error: Mapped[str | None] = mapped_column(Text)
    failure_page: Mapped[int | None] = mapped_column(Integer)
    job_id: Mapped[PyUUID | None] = mapped_column(UUID)
    correction_pages: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    correction_base: Mapped[PyUUID | None] = mapped_column(UUID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text('clock_timestamp()'))
