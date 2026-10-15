from sqlalchemy import BigInteger, CheckConstraint, Integer, PrimaryKeyConstraint, Text, text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID as PyUUID

from app.models.base import Base


class ServiceState(Base):
    __tablename__ = 'service_state'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='service_state_pkey'),
        CheckConstraint('id = 1', name='service_state_id_check'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    epoch: Mapped[int] = mapped_column(BigInteger, server_default=sql_text('0'))
    runtime_id: Mapped[PyUUID] = mapped_column(UUID, server_default=sql_text('gen_random_uuid()'))
    physical_host: Mapped[str | None] = mapped_column(Text)
