from sqlalchemy import Column, Integer, ForeignKey, Text, Enum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from datetime import datetime, timezone

from app.core.database import Base


class CreditReason(str, enum.Enum):
    PURCHASE = "purchase"
    BOOKING = "booking"
    REFUND = "refund"
    MANUAL = "manual"
    SUBSCRIPTION = "subscription"
    CREDIT_PACK = "credit_pack"


class CreditLedger(Base):
    __tablename__ = "credit_ledger"

    # Foreign key to user
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Credit transaction
    delta = Column(Integer, nullable=False)  # Positive or negative change in credits
    reason = Column(Enum(CreditReason), nullable=False)
    
    # Optional foreign key to booking
    booking_id = Column(UUID(as_uuid=True), ForeignKey("bookings.id"), nullable=True)
    
    # Balance after this transaction
    balance_after = Column(Integer, nullable=False)  # Running balance after this transaction
    
    # Soft delete
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="credit_ledger_entries")
    booking = relationship("Booking", back_populates="credit_ledger_entries")

    def __repr__(self):
        return f"<CreditLedger(user_id={self.user_id}, delta={self.delta}, reason={self.reason}, balance_after={self.balance_after})>"
