from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import selectinload
import uuid
import json
from dateutil import rrule
from dateutil.parser import parse
import pytz

from app.models.availability import AvailabilityBlock, TimeOffBlock, Slot, SlotStatus
from app.models.booking import Booking, BookingStatus
from app.models.user import User, UserRole
from app.models.google_oauth import GoogleOAuthAccount
from app.services.google_calendar_service import GoogleCalendarService
from app.services.notification_service import NotificationService
from app.core.exceptions import SchedulingError, BookingError


class SchedulingService:
    """Comprehensive scheduling service for availability and booking management"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.google_calendar = GoogleCalendarService()
        self.notification_service = NotificationService()
    
    async def create_availability_block(
        self,
        tutor_id: str,
        start_at: datetime,
        end_at: datetime,
        is_recurring: bool = False,
        rrule_string: Optional[str] = None
    ) -> AvailabilityBlock:
        """Create availability block and generate slots"""
        
        # Validate time range
        if start_at >= end_at:
            raise SchedulingError("Start time must be before end time")
        
        if start_at < datetime.now(timezone.utc):
            raise SchedulingError("Cannot create availability in the past")
        
        # Create availability block
        availability = AvailabilityBlock(
            tutor_id=tutor_id,
            start_at=start_at,
            end_at=end_at,
            is_recurring=is_recurring,
            rrule=rrule_string
        )
        
        self.db.add(availability)
        await self.db.commit()
        await self.db.refresh(availability)
        
        # Generate slots for the next 8 weeks
        await self._generate_slots_from_availability(availability)
        
        return availability
    
    async def _generate_slots_from_availability(self, availability: AvailabilityBlock) -> List[Slot]:
        """Generate bookable slots from availability block"""
        slots = []
        
        if availability.is_recurring and availability.rrule:
            # Parse RRULE and generate recurring slots
            rule = rrule.rrulestr(availability.rrule, dtstart=availability.start_at)
            
            # Generate slots for next 8 weeks
            end_date = datetime.now(timezone.utc) + timedelta(weeks=8)
            
            for occurrence in rule.between(
                datetime.now(timezone.utc),
                end_date
            ):
                slot_start = occurrence
                slot_end = occurrence + (availability.end_at - availability.start_at)
                
                # Check for time-off conflicts
                if not await self._has_time_off_conflict(availability.tutor_id, slot_start, slot_end):
                    slot = Slot(
                        tutor_id=availability.tutor_id,
                        start_at=slot_start,
                        end_at=slot_end,
                        status=SlotStatus.OPEN
                    )
                    slots.append(slot)
        else:
            # One-time availability
            if not await self._has_time_off_conflict(availability.tutor_id, availability.start_at, availability.end_at):
                slot = Slot(
                    tutor_id=availability.tutor_id,
                    start_at=availability.start_at,
                    end_at=availability.end_at,
                    status=SlotStatus.OPEN
                )
                slots.append(slot)
        
        # Bulk insert slots
        if slots:
            self.db.add_all(slots)
            await self.db.commit()
        
        return slots
    
    async def _has_time_off_conflict(self, tutor_id: str, start_at: datetime, end_at: datetime) -> bool:
        """Check if time range conflicts with time-off blocks"""
        from app.models.availability import TimeOffBlock
        
        conflict = await self.db.execute(
            select(TimeOffBlock).where(
                and_(
                    TimeOffBlock.tutor_id == tutor_id,
                    TimeOffBlock.deleted_at.is_(None),
                    or_(
                        and_(TimeOffBlock.start_at <= start_at, TimeOffBlock.end_at > start_at),
                        and_(TimeOffBlock.start_at < end_at, TimeOffBlock.end_at >= end_at),
                        and_(TimeOffBlock.start_at >= start_at, TimeOffBlock.end_at <= end_at)
                    )
                )
            )
        ).scalar_one_or_none()
        
        return conflict is not None
    
    async def get_available_slots(
        self,
        tutor_id: str,
        start_date: datetime,
        end_date: datetime,
        student_timezone: str = "UTC"
    ) -> List[Dict[str, Any]]:
        """Get available slots for a tutor, filtered by Google Calendar busy times"""
        
        # Get open slots
        slots = await self.db.execute(
            select(Slot).where(
                and_(
                    Slot.tutor_id == tutor_id,
                    Slot.status == SlotStatus.OPEN,
                    Slot.start_at >= start_date,
                    Slot.start_at <= end_date,
                    Slot.deleted_at.is_(None)
                )
            ).options(selectinload(Slot.tutor))
        ).scalars().all()
        
        # Get Google Calendar busy times if connected
        busy_times = await self._get_google_calendar_busy_times(tutor_id, start_date, end_date)
        
        # Filter out busy times and convert to student timezone
        available_slots = []
        student_tz = pytz.timezone(student_timezone)
        
        for slot in slots:
            # Check if slot conflicts with Google Calendar busy times
            if not self._has_calendar_conflict(slot, busy_times):
                # Convert to student timezone
                slot_start_local = slot.start_at.astimezone(student_tz)
                slot_end_local = slot.end_at.astimezone(student_tz)
                
                available_slots.append({
                    "slot_id": str(slot.id),
                    "start_at": slot.start_at.isoformat(),
                    "end_at": slot.end_at.isoformat(),
                    "start_at_local": slot_start_local.isoformat(),
                    "end_at_local": slot_end_local.isoformat(),
                    "duration_minutes": int((slot.end_at - slot.start_at).total_seconds() / 60)
                })
        
        return available_slots
    
    async def _get_google_calendar_busy_times(self, tutor_id: str, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Get busy times from Google Calendar"""
        try:
            # Get tutor's Google OAuth account
            oauth_account = await self.db.execute(
                select(GoogleOAuthAccount).where(
                    and_(
                        GoogleOAuthAccount.user_id == tutor_id,
                        GoogleOAuthAccount.deleted_at.is_(None)
                    )
                )
            ).scalar_one_or_none()
            
            if oauth_account and oauth_account.calendar_connected:
                return await self.google_calendar.get_busy_times(
                    access_token=oauth_account.access_token,
                    start_date=start_date,
                    end_date=end_date
                )
        except Exception as e:
            # Log error but don't fail the request
            print(f"Error getting Google Calendar busy times: {e}")
        
        return []
    
    def _has_calendar_conflict(self, slot: Slot, busy_times: List[Dict[str, Any]]) -> bool:
        """Check if slot conflicts with Google Calendar busy times"""
        for busy_time in busy_times:
            busy_start = parse(busy_time["start"])
            busy_end = parse(busy_time["end"])
            
            # Check for overlap
            if (slot.start_at < busy_end and slot.end_at > busy_start):
                return True
        
        return False
    
    async def hold_slot(self, slot_id: str, student_id: str, hold_duration_minutes: int = 10) -> Dict[str, Any]:
        """Hold a slot for booking with transaction safety"""
        
        # Use database transaction to prevent race conditions
        async with self.db.begin():
            # Get slot with lock
            slot = await self.db.execute(
                select(Slot).where(
                    and_(
                        Slot.id == slot_id,
                        Slot.status == SlotStatus.OPEN,
                        Slot.deleted_at.is_(None)
                    )
                ).with_for_update()
            ).scalar_one_or_none()
            
            if not slot:
                raise BookingError("Slot not available")
            
            # Check if slot is still available (double-check)
            if slot.status != SlotStatus.OPEN:
                raise BookingError("Slot already booked")
            
            # Update slot status to held
            slot.status = SlotStatus.HELD
            slot.updated_at = datetime.now(timezone.utc)
            
            # Generate hold token
            hold_token = str(uuid.uuid4())
            hold_expires_at = datetime.now(timezone.utc) + timedelta(minutes=hold_duration_minutes)
            
            # Store hold information (in practice, use Redis for this)
            hold_info = {
                "slot_id": slot_id,
                "student_id": student_id,
                "hold_token": hold_token,
                "expires_at": hold_expires_at.isoformat()
            }
            
            await self.db.commit()
            
            return {
                "hold_token": hold_token,
                "expires_at": hold_expires_at.isoformat(),
                "slot_id": slot_id
            }
    
    async def confirm_booking(
        self,
        hold_token: str,
        student_id: str,
        payment_method: str,  # "credit", "stripe", "subscription"
        payment_intent_id: Optional[str] = None
    ) -> Booking:
        """Confirm booking after payment processing"""
        
        # Validate hold token (in practice, get from Redis)
        # For now, we'll assume the token is valid
        
        async with self.db.begin():
            # Get the held slot
            slot = await self.db.execute(
                select(Slot).where(
                    and_(
                        Slot.status == SlotStatus.HELD,
                        Slot.deleted_at.is_(None)
                    )
                ).with_for_update()
            ).scalar_one_or_none()
            
            if not slot:
                raise BookingError("No held slot found")
            
            # Create booking
            booking = Booking(
                student_id=student_id,
                tutor_id=slot.tutor_id,
                start_at=slot.start_at,
                end_at=slot.end_at,
                status=BookingStatus.CONFIRMED,
                price_cents=await self._calculate_booking_price(slot.tutor_id, slot.start_at, slot.end_at),
                payment_intent_id=payment_intent_id,
                slot_id=slot.id
            )
            
            self.db.add(booking)
            
            # Update slot status
            slot.status = SlotStatus.BOOKED
            
            # Create Google Calendar events
            await self._create_calendar_events(booking)
            
            # Send notifications
            await self._send_booking_confirmation(booking)
            
            await self.db.commit()
            await self.db.refresh(booking)
            
            return booking
    
    async def _calculate_booking_price(self, tutor_id: str, start_at: datetime, end_at: datetime) -> int:
        """Calculate booking price based on tutor's hourly rate"""
        from app.models.tutor_profile import TutorProfile
        
        tutor_profile = await self.db.execute(
            select(TutorProfile).where(
                and_(
                    TutorProfile.user_id == tutor_id,
                    TutorProfile.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        
        if not tutor_profile:
            raise BookingError("Tutor profile not found")
        
        duration_hours = (end_at - start_at).total_seconds() / 3600
        return int(tutor_profile.hourly_rate_cents * duration_hours)
    
    async def _create_calendar_events(self, booking: Booking) -> None:
        """Create Google Calendar events for both tutor and student"""
        try:
            # Get tutor and student details
            tutor = await self.db.execute(
                select(User).where(User.id == booking.tutor_id)
            ).scalar_one()
            
            student = await self.db.execute(
                select(User).where(User.id == booking.student_id)
            ).scalar_one()
            
            # Create event for tutor
            if tutor:
                tutor_oauth = await self.db.execute(
                    select(GoogleOAuthAccount).where(
                        and_(
                            GoogleOAuthAccount.user_id == booking.tutor_id,
                            GoogleOAuthAccount.deleted_at.is_(None)
                        )
                    )
                ).scalar_one_or_none()
                
                if tutor_oauth:
                    event_id = await self.google_calendar.create_event(
                        access_token=tutor_oauth.access_token,
                        summary=f"Tutoring Session - {student.name}",
                        description=f"Tutoring session with {student.name}",
                        start_time=booking.start_at,
                        end_time=booking.end_at,
                        attendee_email=student.email
                    )
                    booking.calendar_event_id_tutor = event_id
            
            # Create event for student
            student_oauth = await self.db.execute(
                select(GoogleOAuthAccount).where(
                    and_(
                        GoogleOAuthAccount.user_id == booking.student_id,
                        GoogleOAuthAccount.deleted_at.is_(None)
                    )
                )
            ).scalar_one_or_none()
            
            if student_oauth:
                event_id = await self.google_calendar.create_event(
                    access_token=student_oauth.access_token,
                    summary=f"Tutoring Session - {tutor.name}",
                    description=f"Tutoring session with {tutor.name}",
                    start_time=booking.start_at,
                    end_time=booking.end_at,
                    attendee_email=tutor.email
                )
                booking.calendar_event_id_student = event_id
                
        except Exception as e:
            # Log error but don't fail the booking
            print(f"Error creating calendar events: {e}")
    
    async def _send_booking_confirmation(self, booking: Booking) -> None:
        """Send booking confirmation notifications"""
        try:
            # Send email notifications
            await self.notification_service.send_booking_confirmation_email(booking)
            
            # Send in-app notifications
            await self.notification_service.send_booking_confirmation_notification(booking)
            
        except Exception as e:
            # Log error but don't fail the booking
            print(f"Error sending booking confirmation: {e}")
    
    async def cancel_booking(self, booking_id: str, reason: str = "Cancelled by user") -> Booking:
        """Cancel a booking with proper refund handling"""
        
        async with self.db.begin():
            booking = await self.db.execute(
                select(Booking).where(
                    and_(
                        Booking.id == booking_id,
                        Booking.deleted_at.is_(None)
                    )
                ).with_for_update()
            ).scalar_one_or_none()
            
            if not booking:
                raise BookingError("Booking not found")
            
            if booking.status in [BookingStatus.CANCELED, BookingStatus.COMPLETED]:
                raise BookingError("Booking cannot be cancelled")
            
            # Update booking status
            booking.status = BookingStatus.CANCELED
            booking.notes = f"{booking.notes or ''}\nCancelled: {reason}"
            
            # Free up the slot
            if booking.slot_id:
                slot = await self.db.execute(
                    select(Slot).where(Slot.id == booking.slot_id)
                ).scalar_one()
                if slot:
                    slot.status = SlotStatus.OPEN
            
            # Handle refunds
            await self._process_cancellation_refund(booking)
            
            # Cancel calendar events
            await self._cancel_calendar_events(booking)
            
            # Send cancellation notifications
            await self._send_cancellation_notifications(booking)
            
            await self.db.commit()
            await self.db.refresh(booking)
            
            return booking
    
    async def _process_cancellation_refund(self, booking: Booking) -> None:
        """Process refund for cancelled booking"""
        # This would integrate with your payment service
        # For now, we'll just log the refund requirement
        print(f"Refund required for booking {booking.id}: {booking.price_cents} cents")
    
    async def _cancel_calendar_events(self, booking: Booking) -> None:
        """Cancel Google Calendar events"""
        try:
            # Cancel tutor's event
            if booking.calendar_event_id_tutor:
                tutor_oauth = await self.db.execute(
                    select(GoogleOAuthAccount).where(
                        and_(
                            GoogleOAuthAccount.user_id == booking.tutor_id,
                            GoogleOAuthAccount.deleted_at.is_(None)
                        )
                    )
                ).scalar_one_or_none()
                
                if tutor_oauth:
                    await self.google_calendar.delete_event(
                        access_token=tutor_oauth.access_token,
                        event_id=booking.calendar_event_id_tutor
                    )
            
            # Cancel student's event
            if booking.calendar_event_id_student:
                student_oauth = await self.db.execute(
                    select(GoogleOAuthAccount).where(
                        and_(
                            GoogleOAuthAccount.user_id == booking.student_id,
                            GoogleOAuthAccount.deleted_at.is_(None)
                        )
                    )
                ).scalar_one_or_none()
                
                if student_oauth:
                    await self.google_calendar.delete_event(
                        access_token=student_oauth.access_token,
                        event_id=booking.calendar_event_id_student
                    )
                    
        except Exception as e:
            print(f"Error cancelling calendar events: {e}")
    
    async def _send_cancellation_notifications(self, booking: Booking) -> None:
        """Send cancellation notifications"""
        try:
            await self.notification_service.send_booking_cancellation_notification(booking)
        except Exception as e:
            print(f"Error sending cancellation notifications: {e}")
    
    async def reschedule_booking(
        self,
        booking_id: str,
        new_slot_id: str,
        reason: str = "Rescheduled by user"
    ) -> Booking:
        """Reschedule a booking to a new slot"""
        
        async with self.db.begin():
            # Get original booking
            booking = await self.db.execute(
                select(Booking).where(
                    and_(
                        Booking.id == booking_id,
                        Booking.deleted_at.is_(None)
                    )
                ).with_for_update()
            ).scalar_one_or_none()
            
            if not booking:
                raise BookingError("Booking not found")
            
            if booking.status in [BookingStatus.CANCELED, BookingStatus.COMPLETED]:
                raise BookingError("Booking cannot be rescheduled")
            
            # Get new slot
            new_slot = await self.db.execute(
                select(Slot).where(
                    and_(
                        Slot.id == new_slot_id,
                        Slot.status == SlotStatus.OPEN,
                        Slot.deleted_at.is_(None)
                    )
                ).with_for_update()
            ).scalar_one_or_none()
            
            if not new_slot:
                raise BookingError("New slot not available")
            
            # Cancel original booking
            await self.cancel_booking(booking_id, f"Rescheduled to {new_slot.start_at}")
            
            # Create new booking
            new_booking = Booking(
                student_id=booking.student_id,
                tutor_id=booking.tutor_id,
                start_at=new_slot.start_at,
                end_at=new_slot.end_at,
                status=BookingStatus.CONFIRMED,
                price_cents=booking.price_cents,
                payment_intent_id=booking.payment_intent_id,
                slot_id=new_slot.id,
                notes=f"Rescheduled from {booking.start_at}. Reason: {reason}"
            )
            
            self.db.add(new_booking)
            
            # Update new slot status
            new_slot.status = SlotStatus.BOOKED
            
            # Create new calendar events
            await self._create_calendar_events(new_booking)
            
            # Send reschedule notifications
            await self._send_reschedule_notifications(new_booking, booking)
            
            await self.db.commit()
            await self.db.refresh(new_booking)
            
            return new_booking
    
    async def _send_reschedule_notifications(self, new_booking: Booking, old_booking: Booking) -> None:
        """Send reschedule notifications"""
        try:
            await self.notification_service.send_booking_reschedule_notification(new_booking, old_booking)
        except Exception as e:
            print(f"Error sending reschedule notifications: {e}")
