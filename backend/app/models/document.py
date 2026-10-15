from sqlalchemy import Boolean, ForeignKeyConstraint, PrimaryKeyConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID as PyUUID

from app.models.base import Base


class Document(Base):
    __tablename__ = 'documents'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='documents_pkey'),
        ForeignKeyConstraint(['id', 'published_revision'], ['source_revisions.document_id', 'source_revisions.id'], name='documents_id_published_revision_fkey', use_alter=True),
        ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='documents_owner_id_fkey'),
    )

    id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    owner_id: Mapped[PyUUID] = mapped_column(UUID)
    ready: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
    deleted: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
    published_revision: Mapped[PyUUID | None] = mapped_column(UUID)
