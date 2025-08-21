from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class GoogleOAuthAccount(Base):
    __tablename__ = "google_oauth_accounts"

    # Foreign key to user
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # OAuth provider (always 'google' for this table)
    provider = Column(String, default="google", nullable=False)
    
    # Encrypted tokens (should be encrypted at application level)
    access_token = Column(Text, nullable=False)  # Encrypted access token
    refresh_token = Column(Text, nullable=True)  # Encrypted refresh token
    
    # Token expiry
    expiry = Column(DateTime(timezone=True), nullable=True)  # When access token expires
    
    # OAuth scopes
    scopes = Column(Text, nullable=True)  # JSON string of granted scopes
    
    # Relationships
    user = relationship("User", back_populates="google_oauth_accounts")

    def __repr__(self):
        return f"<GoogleOAuthAccount(user_id={self.user_id}, provider={self.provider})>"
