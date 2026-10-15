from sqlalchemy import BigInteger, CheckConstraint, Integer, PrimaryKeyConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from typing import Any

from app.models.base import Base


class Setting(Base):
    __tablename__ = 'settings'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='settings_pkey'),
        CheckConstraint('id = 1', name='settings_id_check'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    overrides: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=sql_text("'{}'::jsonb"))
    revision: Mapped[int] = mapped_column(BigInteger, server_default=sql_text('0'))
    applied_revision: Mapped[int] = mapped_column(BigInteger, server_default=sql_text('0'))
