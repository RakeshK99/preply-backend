from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text, Enum, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.core.database import Base


class AvailabilityBlock(Base):
    __tablename__ = "availability_blocks"

    # Foreign key to tutor
    tutor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Time information
    start_at = Column(DateTime(timezone=True), nullable=False)  # UTC
    end_at = Column(DateTime(timezone=True), nullable=False)  # UTC
    
    # Recurring settings
    rrule = Column(Text, nullable=True)  # iCalendar RRULE string for recurring events
    is_recurring = Column(Boolean, default=False, nullable=False)
    
    # Relationships
    tutor = relationship("User", back_populates="availability_blocks")

    def __repr__(self):
        return f"<AvailabilityBlock(tutor_id={self.tutor_id}, start_at={self.start_at}, end_at={self.end_at})>"


class TimeOffBlock(Base):
    __tablename__ = "time_off_blocks"

    # Foreign key to tutor
    tutor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Time information
    start_at = Column(DateTime(timezone=True), nullable=False)  # UTC
    end_at = Column(DateTime(timezone=True), nullable=False)  # UTC
    
    # Relationships
    tutor = relationship("User", back_populates="time_off_blocks")

    def __repr__(self):
        return f"<TimeOffBlock(tutor_id={self.tutor_id}, start_at={self.start_at}, end_at={self.end_at})>"


class SlotStatus(str, enum.Enum):
    OPEN = "open"
    HELD = "held"
    BOOKED = "booked"
    CLOSED = "closed"


class Slot(Base):
    __tablename__ = "slots"

    # Foreign key to tutor
    tutor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Time information
    start_at = Column(DateTime(timezone=True), nullable=False)  # UTC
    end_at = Column(DateTime(timezone=True), nullable=False)  # UTC
    
    # Status
    status = Column(Enum(SlotStatus), default=SlotStatus.OPEN, nullable=False)
    
    # Relationships
    tutor = relationship("User", back_populates="slots")
    booking = relationship("Booking", back_populates="slot", uselist=False)

    def __repr__(self):
        return f"<Slot(tutor_id={self.tutor_id}, start_at={self.start_at}, status={self.status})>"


# Create unique index to prevent double-booking
Index('idx_slots_tutor_start_unique', Slot.tutor_id, Slot.start_at, unique=True)
