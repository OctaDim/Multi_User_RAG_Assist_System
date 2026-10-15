from sqlalchemy import BigInteger, Boolean, ForeignKeyConstraint, PrimaryKeyConstraint, Text, UniqueConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID as PyUUID

from app.models.base import Base


class GraphBinding(Base):
    __tablename__ = 'graph_bindings'
    __table_args__ = (
        PrimaryKeyConstraint('request_id', name='graph_bindings_pkey'),
        UniqueConstraint('thread_id', name='graph_bindings_thread_id_key'),
        ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name='graph_bindings_conversation_id_fkey'),
        ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='graph_bindings_owner_id_fkey'),
        ForeignKeyConstraint(['request_id'], ['requests.id'], name='graph_bindings_request_id_fkey'),
    )

    request_id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    thread_id: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[PyUUID] = mapped_column(UUID)
    conversation_id: Mapped[PyUUID] = mapped_column(UUID)
    execution_epoch: Mapped[int] = mapped_column(BigInteger)
    context_epoch: Mapped[int] = mapped_column(BigInteger)
    account_epoch: Mapped[int] = mapped_column(BigInteger)
    started: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
