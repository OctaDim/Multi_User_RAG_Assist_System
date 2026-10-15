from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer, PrimaryKeyConstraint, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID as PyUUID

from app.models.base import Base


class SourcePage(Base):
    __tablename__ = 'source_pages'
    __table_args__ = (
        PrimaryKeyConstraint('revision_id', 'page', name='source_pages_pkey'),
        ForeignKeyConstraint(['revision_id'], ['source_revisions.id'], name='source_pages_revision_id_fkey'),
        CheckConstraint('page > 0', name='source_pages_page_check'),
        CheckConstraint("status = ANY (ARRAY['ready'::text, 'failed'::text, 'processing'::text])", name='source_pages_status_check'),
    )

    revision_id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    page: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    status: Mapped[str] = mapped_column(Text)
