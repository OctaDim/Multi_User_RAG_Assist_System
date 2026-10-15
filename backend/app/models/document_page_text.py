from sqlalchemy import ForeignKeyConstraint, Integer, PrimaryKeyConstraint, Text, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from typing import Any
from uuid import UUID as PyUUID

from app.models.base import Base


class DocumentPageText(Base):
    __tablename__ = 'document_page_texts'
    __table_args__ = (
        PrimaryKeyConstraint('revision_id', 'page', name='document_page_texts_pkey'),
        ForeignKeyConstraint(['revision_id', 'page'], ['source_pages.revision_id', 'source_pages.page'], name='document_page_texts_revision_id_page_fkey'),
    )

    revision_id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    page: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    text: Mapped[str] = mapped_column(Text)
    regions: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=sql_text("'[]'::jsonb"))
