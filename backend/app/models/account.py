from sqlalchemy import BigInteger, Boolean, CheckConstraint, PrimaryKeyConstraint, Text, UniqueConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID as PyUUID

from app.models.base import Base


class Account(Base):
    __tablename__ = 'accounts'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='accounts_pkey'),
        UniqueConstraint('email', name='accounts_email_key'),
        CheckConstraint('(email IS NULL) = (password_hash IS NULL)', name='account_credentials_pair'),
        CheckConstraint("role = ANY (ARRAY['user'::text, 'admin'::text, 'super_admin'::text])", name='accounts_role_check'),
    )

    id: Mapped[PyUUID] = mapped_column(UUID, primary_key=True)
    role: Mapped[str] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
    active: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('true'))
    disabled: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
    paid: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
    context_epoch: Mapped[int] = mapped_column(BigInteger, server_default=sql_text('0'))
    email: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
