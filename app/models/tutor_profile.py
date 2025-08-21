from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class TutorProfile(Base):
    __tablename__ = "tutor_profiles"

    # Foreign key to user
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    
    # Profile information
    bio = Column(Text, nullable=True)
    subjects = Column(ARRAY(String), nullable=False, default=[])  # Array of subject strings
    hourly_rate_cents = Column(Integer, nullable=False)  # Rate in cents
    
    # Meeting and calendar settings
    meeting_link = Column(String, nullable=True)  # Default meeting link (Zoom, Google Meet, etc.)
    calendar_connected = Column(Boolean, default=False, nullable=False)
    google_calendar_primary_id = Column(String, nullable=True)  # Primary calendar ID
    
    # Relationships
    user = relationship("User", back_populates="tutor_profile")

    def __repr__(self):
        return f"<TutorProfile(user_id={self.user_id}, subjects={self.subjects})>"
