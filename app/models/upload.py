from sqlalchemy import Column, String, Integer, ForeignKey, Text, Boolean, Enum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from datetime import datetime, timezone

from app.core.database import Base


class UploadOrigin(str, enum.Enum):
    NOTES = "notes"
    SLIDES = "slides"
    ASSIGNMENT = "assignment"


class Upload(Base):
    __tablename__ = "uploads"

    # Foreign key to user
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # File information
    file_key = Column(String, nullable=False)  # S3 key or file path
    mime = Column(String, nullable=False)  # MIME type
    bytes = Column(Integer, nullable=False)  # File size in bytes
    origin = Column(Enum(UploadOrigin), nullable=False)  # Purpose of upload
    
    # Processing status
    processed = Column(Boolean, default=False, nullable=False)  # Whether AI processing is complete
    
    # Soft delete
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="uploads")
    ai_artifacts = relationship("AIArtifact", back_populates="upload")

    def __repr__(self):
        return f"<Upload(user_id={self.user_id}, file_key={self.file_key}, origin={self.origin}, processed={self.processed})>"
