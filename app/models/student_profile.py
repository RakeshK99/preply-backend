from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    # Foreign key to user
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    
    # Profile information
    school = Column(String, nullable=True)
    grade = Column(String, nullable=True)  # e.g., "10th grade", "Sophomore", "Year 2"
    goals = Column(Text, nullable=True)  # Learning goals and objectives
    
    # Calendar integration
    calendar_connected = Column(Boolean, default=False, nullable=False)
    google_calendar_primary_id = Column(String, nullable=True)  # Primary calendar ID
    
    # Credits and billing
    credit_balance = Column(Integer, default=0, nullable=False)  # Available credits
    
    # Relationships
    user = relationship("User", back_populates="student_profile")

    def __repr__(self):
        return f"<StudentProfile(user_id={self.user_id}, school={self.school}, credit_balance={self.credit_balance})>"
