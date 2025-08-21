from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel, Field
import pytz
import json

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User, UserRole
from app.models.availability import AvailabilityBlock, TimeOffBlock, Slot, SlotStatus
from app.models.booking import Booking, BookingStatus
from app.models.tutor_profile import TutorProfile
from app.models.student_profile import StudentProfile
from app.services.scheduling_service import SchedulingService
from app.services.google_calendar_service import GoogleCalendarService
from app.core.exceptions import SchedulingError, BookingError


router = APIRouter()


# Pydantic models for request/response
class AvailabilityBlockCreate(BaseModel):
    start_at: datetime = Field(..., description="Start time in UTC")
    end_at: datetime = Field(..., description="End time in UTC")
    is_recurring: bool = Field(False, description="Whether this is a recurring availability")
    rrule_string: Optional[str] = Field(None, description="iCalendar RRULE string for recurring events")


class TimeOffBlockCreate(BaseModel):
    start_at: datetime = Field(..., description="Start time in UTC")
    end_at: datetime = Field(..., description="End time in UTC")


class SlotResponse(BaseModel):
    slot_id: str
    start_at: str
    end_at: str
    start_at_local: str
    end_at_local: str
    duration_minutes: int


class BookingCreate(BaseModel):
    slot_id: str = Field(..., description="ID of the slot to book")
    payment_method: str = Field(..., description="Payment method: credit, stripe, subscription")
    payment_intent_id: Optional[str] = Field(None, description="Stripe payment intent ID")


class BookingResponse(BaseModel):
    booking_id: str
    tutor_id: str
    student_id: str
    start_at: str
    end_at: str
    status: str
    price_cents: int
    join_link: Optional[str]
    notes: Optional[str]


class BookingCancelRequest(BaseModel):
    reason: str = Field("Cancelled by user", description="Reason for cancellation")


class BookingRescheduleRequest(BaseModel):
    new_slot_id: str = Field(..., description="ID of the new slot")
    reason: str = Field("Rescheduled by user", description="Reason for rescheduling")


# Availability Management Endpoints
@router.post("/availability", response_model=dict)
async def create_availability_block(
    availability: AvailabilityBlockCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create availability block for tutor"""
    if current_user.role != UserRole.TUTOR:
        raise HTTPException(status_code=403, detail="Only tutors can create availability")
    
    try:
        scheduling_service = SchedulingService(db)
        availability_block = await scheduling_service.create_availability_block(
            tutor_id=str(current_user.id),
            start_at=availability.start_at,
            end_at=availability.end_at,
            is_recurring=availability.is_recurring,
            rrule_string=availability.rrule_string
        )
        
        return {
            "message": "Availability block created successfully",
            "availability_id": str(availability_block.id)
        }
    except SchedulingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/availability/time-off", response_model=dict)
async def create_time_off_block(
    time_off: TimeOffBlockCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create time-off block for tutor"""
    if current_user.role != UserRole.TUTOR:
        raise HTTPException(status_code=403, detail="Only tutors can create time-off blocks")
    
    try:
        time_off_block = TimeOffBlock(
            tutor_id=str(current_user.id),
            start_at=time_off.start_at,
            end_at=time_off.end_at
        )
        
        db.add(time_off_block)
        await db.commit()
        await db.refresh(time_off_block)
        
        return {
            "message": "Time-off block created successfully",
            "time_off_id": str(time_off_block.id)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/availability/{tutor_id}/slots", response_model=List[SlotResponse])
async def get_available_slots(
    tutor_id: str,
    start_date: datetime = Query(..., description="Start date in UTC"),
    end_date: datetime = Query(..., description="End date in UTC"),
    timezone: str = Query("UTC", description="Student's timezone"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get available slots for a tutor"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can view available slots")
    
    try:
        # Validate timezone
        try:
            pytz.timezone(timezone)
        except pytz.exceptions.UnknownTimeZoneError:
            timezone = "UTC"
        
        scheduling_service = SchedulingService(db)
        slots = await scheduling_service.get_available_slots(
            tutor_id=tutor_id,
            start_date=start_date,
            end_date=end_date,
            student_timezone=timezone
        )
        
        return slots
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/availability/my-slots", response_model=List[SlotResponse])
async def get_my_availability(
    start_date: datetime = Query(..., description="Start date in UTC"),
    end_date: datetime = Query(..., description="End date in UTC"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get tutor's own availability slots"""
    if current_user.role != UserRole.TUTOR:
        raise HTTPException(status_code=403, detail="Only tutors can view their availability")
    
    try:
        scheduling_service = SchedulingService(db)
        slots = await scheduling_service.get_available_slots(
            tutor_id=str(current_user.id),
            start_date=start_date,
            end_date=end_date,
            student_timezone=current_user.timezone
        )
        
        return slots
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Booking Endpoints
@router.post("/booking/hold", response_model=dict)
async def hold_slot(
    slot_id: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Hold a slot for booking"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can hold slots")
    
    try:
        scheduling_service = SchedulingService(db)
        hold_info = await scheduling_service.hold_slot(
            slot_id=slot_id,
            student_id=str(current_user.id)
        )
        
        return {
            "message": "Slot held successfully",
            "hold_token": hold_info["hold_token"],
            "expires_at": hold_info["expires_at"]
        }
    except BookingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/booking/confirm", response_model=BookingResponse)
async def confirm_booking(
    booking: BookingCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Confirm booking after payment"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can confirm bookings")
    
    try:
        scheduling_service = SchedulingService(db)
        confirmed_booking = await scheduling_service.confirm_booking(
            hold_token=booking.slot_id,  # In practice, this would be the actual hold token
            student_id=str(current_user.id),
            payment_method=booking.payment_method,
            payment_intent_id=booking.payment_intent_id
        )
        
        return BookingResponse(
            booking_id=str(confirmed_booking.id),
            tutor_id=str(confirmed_booking.tutor_id),
            student_id=str(confirmed_booking.student_id),
            start_at=confirmed_booking.start_at.isoformat(),
            end_at=confirmed_booking.end_at.isoformat(),
            status=confirmed_booking.status.value,
            price_cents=confirmed_booking.price_cents,
            join_link=confirmed_booking.join_link,
            notes=confirmed_booking.notes
        )
    except BookingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/bookings", response_model=List[BookingResponse])
async def get_my_bookings(
    status: Optional[str] = Query(None, description="Filter by booking status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's bookings"""
    try:
        query = select(Booking).where(
            and_(
                Booking.deleted_at.is_(None),
                (Booking.student_id == str(current_user.id) | Booking.tutor_id == str(current_user.id))
            )
        )
        
        if status:
            query = query.where(Booking.status == status)
        
        query = query.order_by(Booking.start_at.desc())
        
        bookings = await db.execute(query)
        booking_list = bookings.scalars().all()
        
        return [
            BookingResponse(
                booking_id=str(booking.id),
                tutor_id=str(booking.tutor_id),
                student_id=str(booking.student_id),
                start_at=booking.start_at.isoformat(),
                end_at=booking.end_at.isoformat(),
                status=booking.status.value,
                price_cents=booking.price_cents,
                join_link=booking.join_link,
                notes=booking.notes
            )
            for booking in booking_list
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/bookings/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get specific booking details"""
    try:
        booking = await db.execute(
            select(Booking).where(
                and_(
                    Booking.id == booking_id,
                    Booking.deleted_at.is_(None),
                    (Booking.student_id == str(current_user.id) | Booking.tutor_id == str(current_user.id))
                )
            )
        ).scalar_one_or_none()
        
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        return BookingResponse(
            booking_id=str(booking.id),
            tutor_id=str(booking.tutor_id),
            student_id=str(booking.student_id),
            start_at=booking.start_at.isoformat(),
            end_at=booking.end_at.isoformat(),
            status=booking.status.value,
            price_cents=booking.price_cents,
            join_link=booking.join_link,
            notes=booking.notes
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/bookings/{booking_id}/cancel", response_model=BookingResponse)
async def cancel_booking(
    booking_id: str,
    cancel_request: BookingCancelRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel a booking"""
    try:
        # Verify user owns the booking
        booking = await db.execute(
            select(Booking).where(
                and_(
                    Booking.id == booking_id,
                    Booking.deleted_at.is_(None),
                    (Booking.student_id == str(current_user.id) | Booking.tutor_id == str(current_user.id))
                )
            )
        ).scalar_one_or_none()
        
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        scheduling_service = SchedulingService(db)
        cancelled_booking = await scheduling_service.cancel_booking(
            booking_id=booking_id,
            reason=cancel_request.reason
        )
        
        return BookingResponse(
            booking_id=str(cancelled_booking.id),
            tutor_id=str(cancelled_booking.tutor_id),
            student_id=str(cancelled_booking.student_id),
            start_at=cancelled_booking.start_at.isoformat(),
            end_at=cancelled_booking.end_at.isoformat(),
            status=cancelled_booking.status.value,
            price_cents=cancelled_booking.price_cents,
            join_link=cancelled_booking.join_link,
            notes=cancelled_booking.notes
        )
    except BookingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/bookings/{booking_id}/reschedule", response_model=BookingResponse)
async def reschedule_booking(
    booking_id: str,
    reschedule_request: BookingRescheduleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Reschedule a booking"""
    try:
        # Verify user owns the booking
        booking = await db.execute(
            select(Booking).where(
                and_(
                    Booking.id == booking_id,
                    Booking.deleted_at.is_(None),
                    (Booking.student_id == str(current_user.id) | Booking.tutor_id == str(current_user.id))
                )
            )
        ).scalar_one_or_none()
        
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        scheduling_service = SchedulingService(db)
        rescheduled_booking = await scheduling_service.reschedule_booking(
            booking_id=booking_id,
            new_slot_id=reschedule_request.new_slot_id,
            reason=reschedule_request.reason
        )
        
        return BookingResponse(
            booking_id=str(rescheduled_booking.id),
            tutor_id=str(rescheduled_booking.tutor_id),
            student_id=str(rescheduled_booking.student_id),
            start_at=rescheduled_booking.start_at.isoformat(),
            end_at=rescheduled_booking.end_at.isoformat(),
            status=rescheduled_booking.status.value,
            price_cents=rescheduled_booking.price_cents,
            join_link=rescheduled_booking.join_link,
            notes=rescheduled_booking.notes
        )
    except BookingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Google Calendar Integration Endpoints
@router.get("/calendar/auth-url")
async def get_google_calendar_auth_url(
    current_user: User = Depends(get_current_user)
):
    """Get Google Calendar OAuth authorization URL"""
    try:
        google_calendar = GoogleCalendarService()
        auth_url = google_calendar.get_authorization_url(state=str(current_user.id))
        
        return {
            "auth_url": auth_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/calendar/connect")
async def connect_google_calendar(
    code: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Connect Google Calendar account"""
    try:
        google_calendar = GoogleCalendarService()
        tokens = await google_calendar.exchange_code_for_tokens(code)
        
        # Store OAuth tokens in database
        from app.models.google_oauth import GoogleOAuthAccount
        
        oauth_account = GoogleOAuthAccount(
            user_id=str(current_user.id),
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            expiry=tokens["expiry"],
            scopes=json.dumps(tokens["scopes"])
        )
        
        db.add(oauth_account)
        await db.commit()
        await db.refresh(oauth_account)
        
        # Update user profile to indicate calendar connection
        if current_user.role == UserRole.TUTOR:
            tutor_profile = await db.execute(
                select(TutorProfile).where(TutorProfile.user_id == str(current_user.id))
            ).scalar_one_or_none()
            
            if tutor_profile:
                tutor_profile.calendar_connected = True
                await db.commit()
        elif current_user.role == UserRole.STUDENT:
            student_profile = await db.execute(
                select(StudentProfile).where(StudentProfile.user_id == str(current_user.id))
            ).scalar_one_or_none()
            
            if student_profile:
                student_profile.calendar_connected = True
                await db.commit()
        
        return {
            "message": "Google Calendar connected successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/calendar/calendars")
async def get_google_calendars(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's Google Calendar list"""
    try:
        from app.models.google_oauth import GoogleOAuthAccount
        
        oauth_account = await db.execute(
            select(GoogleOAuthAccount).where(
                and_(
                    GoogleOAuthAccount.user_id == str(current_user.id),
                    GoogleOAuthAccount.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        
        if not oauth_account:
            raise HTTPException(status_code=404, detail="Google Calendar not connected")
        
        google_calendar = GoogleCalendarService()
        calendars = await google_calendar.get_calendar_list(oauth_account.access_token)
        
        return {
            "calendars": calendars
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/calendar/disconnect")
async def disconnect_google_calendar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Disconnect Google Calendar account"""
    try:
        from app.models.google_oauth import GoogleOAuthAccount
        
        oauth_account = await db.execute(
            select(GoogleOAuthAccount).where(
                and_(
                    GoogleOAuthAccount.user_id == str(current_user.id),
                    GoogleOAuthAccount.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        
        if oauth_account:
            oauth_account.deleted_at = datetime.now(timezone.utc)
            await db.commit()
        
        # Update user profile
        if current_user.role == UserRole.TUTOR:
            tutor_profile = await db.execute(
                select(TutorProfile).where(TutorProfile.user_id == str(current_user.id))
            ).scalar_one_or_none()
            
            if tutor_profile:
                tutor_profile.calendar_connected = False
                await db.commit()
        elif current_user.role == UserRole.STUDENT:
            student_profile = await db.execute(
                select(StudentProfile).where(StudentProfile.user_id == str(current_user.id))
            ).scalar_one_or_none()
            
            if student_profile:
                student_profile.calendar_connected = False
                await db.commit()
        
        return {
            "message": "Google Calendar disconnected successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")
