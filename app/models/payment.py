from sqlalchemy import Column, String, Integer, ForeignKey, Text, Enum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from datetime import datetime, timezone

from app.core.database import Base


class PaymentType(str, enum.Enum):
    SUBSCRIPTION = "subscription"
    ONE_OFF = "one_off"
    CREDIT_PACK = "credit_pack"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class Payment(Base):
    __tablename__ = "payments"

    # Foreign key to user
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Optional foreign key to booking
    booking_id = Column(UUID(as_uuid=True), ForeignKey("bookings.id"), nullable=True)
    
    # Payment details
    stripe_payment_intent_id = Column(String, unique=True, nullable=False)
    amount_cents = Column(Integer, nullable=False)  # Amount in cents
    type = Column(Enum(PaymentType), nullable=False)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)
    
    # Soft delete
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="payments")
    booking = relationship("Booking", back_populates="payments")

    def __repr__(self):
        return f"<Payment(user_id={self.user_id}, amount_cents={self.amount_cents}, type={self.type}, status={self.status})>"
