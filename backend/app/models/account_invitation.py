from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, PrimaryKeyConstraint, Text, text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AccountInvitation(Base):
    __tablename__ = 'account_invitations'
    __table_args__ = (
        PrimaryKeyConstraint('token_hash', name='account_invitations_pkey'),
        CheckConstraint("role = 'super_admin'::text", name='account_invitations_role_check'),
    )

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, server_default=sql_text('false'))
