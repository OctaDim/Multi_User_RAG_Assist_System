from datetime import datetime
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CoordinatorLease(Base):
    __tablename__ = 'coordinator_lease'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='coordinator_lease_pkey'),
        CheckConstraint('id = 1', name='coordinator_lease_id_check'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    epoch: Mapped[int] = mapped_column(BigInteger)
    healthy_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
