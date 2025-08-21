from fastapi import APIRouter, Depends, HTTPException, status, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
import uuid
import redis.asyncio as redis

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User, UserRole
from app.models.booking import Booking, BookingStatus
from app.models.availability import AvailabilityBlock
from app.schemas.booking import (
    BookingHoldRequest, 
    BookingHoldResponse,
    BookingConfirmRequest,
    BookingRescheduleRequest,
    BookingCancelRequest,
    BookingListResponse
)
from app.services.stripe_service import StripeService
from app.services.availability_service import AvailabilityService
from app.services.calendar_service import CalendarService
from app.core.config import settings

router = APIRouter()

# Redis client for holds
# redis_client = redis.from_url(settings.REDIS_URL)
redis_client = None


@router.post("/book/hold", response_model=BookingHoldResponse)
async def hold_slot(
    request: BookingHoldRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Hold a slot (returns hold_id, expires_at)"""
    try:
        # Validate user can book
        if current_user.role not in [UserRole.STUDENT, UserRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only students can book sessions"
            )
        
        # Check if slot is available
        availability_service = AvailabilityService()
        is_available = await availability_service.check_slot_availability(
            request.tutor_id,
            request.start_time,
            request.end_time,
            db
        )
        
        if not is_available:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Slot is not available"
            )
        
        # Generate hold ID
        hold_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)  # 15 minute hold
        
        # Store hold in Redis with TTL
        hold_data = {
            "user_id": str(current_user.id),
            "tutor_id": request.tutor_id,
            "start_time": request.start_time.isoformat(),
            "end_time": request.end_time.isoformat(),
            "subject": request.subject,
            "notes": request.notes
        }
        
        await redis_client.setex(
            f"booking_hold:{hold_id}",
            900,  # 15 minutes in seconds
            str(hold_data)
        )
        
        # Mark slot as held in database
        await availability_service.mark_slot_held(
            request.tutor_id,
            request.start_time,
            request.end_time,
            hold_id,
            db
        )
        
        return {
            "hold_id": hold_id,
            "expires_at": expires_at.isoformat(),
            "tutor_id": request.tutor_id,
            "start_time": request.start_time.isoformat(),
            "end_time": request.end_time.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to hold slot: {str(e)}"
        )


@router.post("/book/confirm")
async def confirm_booking(
    request: BookingConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Pay with credit or stripe, create booking, create calendar events"""
    try:
        # Validate user can book
        if current_user.role not in [UserRole.STUDENT, UserRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only students can book sessions"
            )
        
        # Get hold data from Redis
        hold_data = await redis_client.get(f"booking_hold:{request.hold_id}")
        if not hold_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hold expired or not found"
            )
        
        # Parse hold data
        import json
        hold_info = json.loads(hold_data)
        
        # Check if user has enough credits or process payment
        stripe_service = StripeService()
        
        if request.payment_method == "credits":
            # Check credit balance
            credit_balance = await stripe_service.get_user_credit_balance(
                str(current_user.id), 
                db
            )
            
            if credit_balance < 1:  # Assuming 1 credit per session
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient credits"
                )
            
            # Deduct credit
            await stripe_service.deduct_credit(
                str(current_user.id),
                1,
                "session_booking",
                db
            )
            
        elif request.payment_method == "stripe":
            # Process Stripe payment
            payment_result = await stripe_service.process_booking_payment(
                current_user,
                request.stripe_payment_intent_id,
                db
            )
            
            if not payment_result["success"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Payment failed"
                )
        
        # Create booking
        booking = Booking(
            id=uuid.uuid4(),
            student_id=current_user.id,
            tutor_id=hold_info["tutor_id"],
            start_time=datetime.fromisoformat(hold_info["start_time"]),
            end_time=datetime.fromisoformat(hold_info["end_time"]),
            subject=hold_info["subject"],
            notes=hold_info.get("notes"),
            status=BookingStatus.CONFIRMED,
            payment_method=request.payment_method,
            amount_cents=0,  # Will be set based on tutor rate
            created_at=datetime.now(timezone.utc)
        )
        
        db.add(booking)
        await db.commit()
        await db.refresh(booking)
        
        # Create calendar events
        calendar_service = CalendarService()
        await calendar_service.create_booking_events(booking, db)
        
        # Remove hold from Redis
        await redis_client.delete(f"booking_hold:{request.hold_id}")
        
        # Release held slot
        availability_service = AvailabilityService()
        await availability_service.release_held_slot(
            hold_info["tutor_id"],
            datetime.fromisoformat(hold_info["start_time"]),
            datetime.fromisoformat(hold_info["end_time"]),
            db
        )
        
        return {
            "booking_id": str(booking.id),
            "status": "confirmed",
            "start_time": booking.start_time.isoformat(),
            "end_time": booking.end_time.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to confirm booking: {str(e)}"
        )


@router.post("/book/reschedule")
async def reschedule_booking(
    request: BookingRescheduleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Policy checks, new hold -> confirm"""
    try:
        # Get existing booking
        result = await db.execute(
            select(Booking).where(Booking.id == request.booking_id)
        )
        booking = result.scalar_one_or_none()
        
        if not booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found"
            )
        
        # Check if user can reschedule this booking
        if booking.student_id != current_user.id and current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to reschedule this booking"
            )
        
        # Check reschedule policy (e.g., 24 hours notice)
        time_until_session = booking.start_time - datetime.now(timezone.utc)
        if time_until_session < timedelta(hours=24):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reschedule within 24 hours of session"
            )
        
        # Check if new slot is available
        availability_service = AvailabilityService()
        is_available = await availability_service.check_slot_availability(
            booking.tutor_id,
            request.new_start_time,
            request.new_end_time,
            db
        )
        
        if not is_available:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="New slot is not available"
            )
        
        # Update booking times
        booking.start_time = request.new_start_time
        booking.end_time = request.new_end_time
        booking.updated_at = datetime.now(timezone.utc)
        
        db.add(booking)
        await db.commit()
        await db.refresh(booking)
        
        # Update calendar events
        calendar_service = CalendarService()
        await calendar_service.update_booking_events(booking, db)
        
        return {
            "booking_id": str(booking.id),
            "status": "rescheduled",
            "new_start_time": booking.start_time.isoformat(),
            "new_end_time": booking.end_time.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reschedule booking: {str(e)}"
        )


@router.post("/book/cancel")
async def cancel_booking(
    request: BookingCancelRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Policy + refunds/cancellations"""
    try:
        # Get existing booking
        result = await db.execute(
            select(Booking).where(Booking.id == request.booking_id)
        )
        booking = result.scalar_one_or_none()
        
        if not booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found"
            )
        
        # Check if user can cancel this booking
        if booking.student_id != current_user.id and current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to cancel this booking"
            )
        
        # Check cancellation policy
        time_until_session = booking.start_time - datetime.now(timezone.utc)
        if time_until_session < timedelta(hours=2):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot cancel within 2 hours of session"
            )
        
        # Process refund if applicable
        stripe_service = StripeService()
        if booking.payment_method == "stripe" and booking.amount_cents > 0:
            refund_result = await stripe_service.process_refund(
                booking,
                request.reason,
                db
            )
        
        # Update booking status
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = datetime.now(timezone.utc)
        booking.cancellation_reason = request.reason
        
        db.add(booking)
        await db.commit()
        await db.refresh(booking)
        
        # Cancel calendar events
        calendar_service = CalendarService()
        await calendar_service.cancel_booking_events(booking, db)
        
        return {
            "booking_id": str(booking.id),
            "status": "cancelled",
            "refund_processed": booking.payment_method == "stripe"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel booking: {str(e)}"
        )


@router.get("/bookings", response_model=List[BookingListResponse])
async def list_bookings(
    role: str = Query(..., description="student or tutor"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List bookings for student or tutor"""
    try:
        # Build query based on role
        if role == "student":
            query = select(Booking).where(Booking.student_id == current_user.id)
        elif role == "tutor":
            query = select(Booking).where(Booking.tutor_id == current_user.id)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Role must be 'student' or 'tutor'"
            )
        
        # Apply status filter
        if status:
            query = query.where(Booking.status == BookingStatus(status))
        
        # Apply pagination
        query = query.order_by(Booking.start_time.desc()).offset(offset).limit(limit)
        
        # Execute query
        result = await db.execute(query)
        bookings = result.scalars().all()
        
        # Convert to response format
        booking_responses = []
        for booking in bookings:
            booking_responses.append({
                "id": str(booking.id),
                "start_time": booking.start_time.isoformat(),
                "end_time": booking.end_time.isoformat(),
                "subject": booking.subject,
                "status": booking.status.value,
                "amount_cents": booking.amount_cents,
                "payment_method": booking.payment_method,
                "created_at": booking.created_at.isoformat()
            })
        
        return booking_responses
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch bookings: {str(e)}"
        )
