import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String, Text

from database import Base


class AccountLevel(str, enum.Enum):
    free = "free"
    trial = "trial"
    paid = "paid"


class User(Base):
    __tablename__ = "users"

    id           = Column(Integer, primary_key=True, index=True)
    username     = Column(String, unique=True, index=True, nullable=False)
    email        = Column(String, unique=True, index=True, nullable=False)
    full_name    = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    account_level = Column(Enum(AccountLevel), default=AccountLevel.trial, nullable=False)
    is_active          = Column(Boolean, default=True, nullable=False)
    created_at         = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login         = Column(DateTime, nullable=True)
    stripe_customer_id = Column(String, nullable=True, unique=True)
    stripe_sub_id      = Column(String, nullable=True, unique=True)
