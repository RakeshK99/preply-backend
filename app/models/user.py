from sqlalchemy import Column, String, Enum, Text, Boolean
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class UserRole(str, enum.Enum):
    STUDENT = "student"
    TUTOR = "tutor"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    # Core user fields
    auth_provider_id = Column(String, unique=True, index=True, nullable=False)  # Clerk user ID
    role = Column(Enum(UserRole), default=UserRole.STUDENT, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    timezone = Column(String, default="UTC", nullable=False)
    
    # Relationships
    tutor_profile = relationship("TutorProfile", back_populates="user", uselist=False)
    student_profile = relationship("StudentProfile", back_populates="user", uselist=False)
    availability_blocks = relationship("AvailabilityBlock", back_populates="tutor")
    time_off_blocks = relationship("TimeOffBlock", back_populates="tutor")
    slots = relationship("Slot", back_populates="tutor")
    bookings_as_student = relationship("Booking", foreign_keys="Booking.student_id", back_populates="student")
    bookings_as_tutor = relationship("Booking", foreign_keys="Booking.tutor_id", back_populates="tutor")
    google_oauth_accounts = relationship("GoogleOAuthAccount", back_populates="user")
    stripe_customer = relationship("StripeCustomer", back_populates="user", uselist=False)
    stripe_subscriptions = relationship("StripeSubscription", back_populates="user")
    payments = relationship("Payment", back_populates="user")
    credit_ledger_entries = relationship("CreditLedger", back_populates="user")
    uploads = relationship("Upload", back_populates="user")
    ai_artifacts = relationship("AIArtifact", back_populates="user")
    messages = relationship("Message", back_populates="user")
    notifications = relationship("Notification", back_populates="user")
    audit_logs_as_actor = relationship("AuditLog", foreign_keys="AuditLog.actor_user_id", back_populates="actor")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
