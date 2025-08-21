from sqlalchemy import Column, String, ForeignKey, Text, Enum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSON
import enum
from datetime import datetime, timezone

from app.core.database import Base


class AIArtifactType(str, enum.Enum):
    FLASHCARDS = "flashcards"
    QUIZ = "quiz"
    SUMMARY = "summary"


class AIArtifactStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AIArtifact(Base):
    __tablename__ = "ai_artifacts"

    # Foreign key to user
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Foreign key to upload (optional)
    upload_id = Column(UUID(as_uuid=True), ForeignKey("uploads.id"), nullable=True)
    
    # Artifact details
    type = Column(Enum(AIArtifactType), nullable=False)
    payload = Column(JSON, nullable=False)  # JSON data containing the generated content
    status = Column(Enum(AIArtifactStatus), default=AIArtifactStatus.PENDING, nullable=False)
    
    # Soft delete
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="ai_artifacts")
    upload = relationship("Upload", back_populates="ai_artifacts")

    def __repr__(self):
        return f"<AIArtifact(user_id={self.user_id}, type={self.type}, status={self.status})>"
