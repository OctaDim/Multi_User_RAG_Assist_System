from sqlalchemy import ForeignKeyConstraint, PrimaryKeyConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID as PyUUID

from app.models.base import Base


class RequestSource(Base):
    __tablename__ = 'request_sources'
    __table_args__ = (
        PrimaryKeyConstraint('request_id', 'document_id', 'revision_id', name='request_sources_pkey'),
        ForeignKeyConstraint(['document_id', 'revision_id'], ['source_revisions.document_id', 'source_revisions.id'], name='request_sources_document_id_revision_id_fkey'),
        ForeignKeyConstraint(['request_id'], ['requests.id'], name='request_sources_request_id_fkey'),
    )

    request_id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    document_id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    revision_id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
