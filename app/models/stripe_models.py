from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from datetime import datetime, timezone

from app.core.database import Base


class StripeCustomer(Base):
    __tablename__ = "stripe_customers"

    # Foreign key to user
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    
    # Stripe customer ID
    stripe_customer_id = Column(String, unique=True, nullable=False)
    
    # Soft delete
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="stripe_customer")

    def __repr__(self):
        return f"<StripeCustomer(user_id={self.user_id}, stripe_customer_id={self.stripe_customer_id})>"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELED = "canceled"
    PAST_DUE = "past_due"
    UNPAID = "unpaid"
    TRIAL = "trial"


class StripeSubscription(Base):
    __tablename__ = "stripe_subscriptions"

    # Foreign key to user
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Stripe subscription details
    stripe_subscription_id = Column(String, unique=True, nullable=False)
    status = Column(Enum(SubscriptionStatus), nullable=False)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    plan_key = Column(String, nullable=False)  # e.g., "starter", "pro", "premium"
    
    # Soft delete
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="stripe_subscriptions")

    def __repr__(self):
        return f"<StripeSubscription(user_id={self.user_id}, plan_key={self.plan_key}, status={self.status})>"
