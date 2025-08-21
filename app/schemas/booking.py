from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class BookingStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    RESCHEDULED = "rescheduled"


class PaymentMethod(str, Enum):
    CREDITS = "credits"
    STRIPE = "stripe"


class BookingHoldRequest(BaseModel):
    tutor_id: str = Field(..., description="Tutor ID")
    start_time: datetime = Field(..., description="Session start time")
    end_time: datetime = Field(..., description="Session end time")
    subject: str = Field(..., description="Subject for the session")
    notes: Optional[str] = Field(None, description="Additional notes")


class BookingHoldResponse(BaseModel):
    hold_id: str = Field(..., description="Unique hold ID")
    expires_at: str = Field(..., description="Hold expiration time")
    tutor_id: str = Field(..., description="Tutor ID")
    start_time: str = Field(..., description="Session start time")
    end_time: str = Field(..., description="Session end time")


class BookingConfirmRequest(BaseModel):
    hold_id: str = Field(..., description="Hold ID from hold endpoint")
    payment_method: PaymentMethod = Field(..., description="Payment method")
    stripe_payment_intent_id: Optional[str] = Field(None, description="Stripe payment intent ID")


class BookingRescheduleRequest(BaseModel):
    booking_id: str = Field(..., description="Booking ID to reschedule")
    new_start_time: datetime = Field(..., description="New session start time")
    new_end_time: datetime = Field(..., description="New session end time")


class BookingCancelRequest(BaseModel):
    booking_id: str = Field(..., description="Booking ID to cancel")
    reason: str = Field(..., description="Cancellation reason")


class BookingListResponse(BaseModel):
    id: str = Field(..., description="Booking ID")
    start_time: str = Field(..., description="Session start time")
    end_time: str = Field(..., description="Session end time")
    subject: str = Field(..., description="Subject")
    status: str = Field(..., description="Booking status")
    amount_cents: int = Field(..., description="Amount in cents")
    payment_method: str = Field(..., description="Payment method")
    created_at: str = Field(..., description="Creation time")


class BookingDetailResponse(BaseModel):
    id: str = Field(..., description="Booking ID")
    student_id: str = Field(..., description="Student ID")
    tutor_id: str = Field(..., description="Tutor ID")
    start_time: str = Field(..., description="Session start time")
    end_time: str = Field(..., description="Session end time")
    subject: str = Field(..., description="Subject")
    notes: Optional[str] = Field(None, description="Additional notes")
    status: BookingStatus = Field(..., description="Booking status")
    amount_cents: int = Field(..., description="Amount in cents")
    payment_method: str = Field(..., description="Payment method")
    created_at: str = Field(..., description="Creation time")
    updated_at: Optional[str] = Field(None, description="Last update time")
    cancelled_at: Optional[str] = Field(None, description="Cancellation time")
    cancellation_reason: Optional[str] = Field(None, description="Cancellation reason")
