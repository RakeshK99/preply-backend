from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.core.database import Base


class BookingStatus(str, enum.Enum):
    PENDING_PAYMENT = "pending_payment"
    CONFIRMED = "confirmed"
    CANCELED = "canceled"
    COMPLETED = "completed"
    REFUNDED = "refunded"


class Booking(Base):
    __tablename__ = "bookings"

    # User relationships
    student_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    tutor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Time information
    start_at = Column(DateTime(timezone=True), nullable=False)  # UTC
    end_at = Column(DateTime(timezone=True), nullable=False)  # UTC
    
    # Status and payment
    status = Column(Enum(BookingStatus), default=BookingStatus.PENDING_PAYMENT, nullable=False)
    price_cents = Column(Integer, nullable=False)  # Price in cents
    payment_intent_id = Column(String, nullable=True)  # Stripe payment intent ID
    
    # Calendar integration
    calendar_event_id_student = Column(String, nullable=True)  # Google Calendar event ID for student
    calendar_event_id_tutor = Column(String, nullable=True)  # Google Calendar event ID for tutor
    
    # Meeting details
    join_link = Column(String, nullable=True)  # Meeting link (Zoom, Google Meet, etc.)
    notes = Column(Text, nullable=True)  # Booking notes
    
    # Slot relationship
    slot_id = Column(UUID(as_uuid=True), ForeignKey("slots.id"), nullable=True)
    
    # Relationships
    student = relationship("User", foreign_keys=[student_id], back_populates="bookings_as_student")
    tutor = relationship("User", foreign_keys=[tutor_id], back_populates="bookings_as_tutor")
    slot = relationship("Slot", back_populates="booking")
    payments = relationship("Payment", back_populates="booking")
    credit_ledger_entries = relationship("CreditLedger", back_populates="booking")

    def __repr__(self):
        return f"<Booking(student_id={self.student_id}, tutor_id={self.tutor_id}, start_at={self.start_at}, status={self.status})>"
