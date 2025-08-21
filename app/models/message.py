from sqlalchemy import Column, String, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.core.database import Base


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(Base):
    __tablename__ = "messages"

    # Foreign key to user
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Message details
    role = Column(Enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    thread_id = Column(String, nullable=False, index=True)  # Thread identifier for conversation grouping
    
    # Relationships
    user = relationship("User", back_populates="messages")

    def __repr__(self):
        return f"<Message(user_id={self.user_id}, role={self.role}, thread_id={self.thread_id})>"
