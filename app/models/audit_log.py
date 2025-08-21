from sqlalchemy import Column, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSON

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    # Actor information
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)  # Null for system actions
    
    # Action details
    action = Column(String, nullable=False)  # e.g., "create", "update", "delete", "login", "payment"
    entity = Column(String, nullable=False)  # e.g., "user", "booking", "payment", "subscription"
    entity_id = Column(String, nullable=True)  # ID of the affected entity (can be UUID or string)
    
    # Change tracking
    diff = Column(JSON, nullable=True)  # JSON object containing before/after values
    
    # Relationships
    actor = relationship("User", foreign_keys=[actor_user_id], back_populates="audit_logs_as_actor")

    def __repr__(self):
        return f"<AuditLog(actor_user_id={self.actor_user_id}, action={self.action}, entity={self.entity}, entity_id={self.entity_id})>"
