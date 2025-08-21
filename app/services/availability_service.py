from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta, date
import pytz
import uuid

from app.models.availability import AvailabilityBlock, SlotStatus
from app.models.booking import Booking, BookingStatus
from app.core.exceptions import AvailabilityError


class AvailabilityService:
    """Service for managing tutor availability and slot checking"""
    
    async def get_tutor_availability(
        self,
        tutor_id: str,
        target_date: Optional[date] = None,
        days_ahead: int = 7,
        timezone: str = "UTC",
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Get tutor's availability for specified period"""
        try:
            # Build query
            query = select(Availability).where(
                and_(
                    Availability.tutor_id == tutor_id,
                    Availability.status == AvailabilityStatus.AVAILABLE
                )
            )
            
            if target_date:
                # Get availability for specific date
                start_of_day = datetime.combine(target_date, datetime.min.time())
                end_of_day = datetime.combine(target_date, datetime.max.time())
                query = query.where(
                    and_(
                        Availability.start_time >= start_of_day,
                        Availability.end_time <= end_of_day
                    )
                )
            else:
                # Get availability for next N days
                now = datetime.now(timezone.utc)
                end_date = now + timedelta(days=days_ahead)
                query = query.where(
                    and_(
                        Availability.start_time >= now,
                        Availability.start_time <= end_date
                    )
                )
            
            result = await db.execute(query)
            availabilities = result.scalars().all()
            
            # Convert to response format
            availability_data = []
            for availability in availabilities:
                availability_data.append({
                    "id": str(availability.id),
                    "start_time": availability.start_time.isoformat(),
                    "end_time": availability.end_time.isoformat(),
                    "status": availability.status.value,
                    "recurring_rule": availability.recurring_rule
                })
            
            return {
                "tutor_id": tutor_id,
                "timezone": timezone,
                "availabilities": availability_data
            }
            
        except Exception as e:
            raise AvailabilityError(f"Failed to get tutor availability: {str(e)}")
    
    async def check_slot_availability(
        self,
        tutor_id: str,
        start_time: datetime,
        end_time: datetime,
        db: AsyncSession
    ) -> bool:
        """Check if a specific time slot is available"""
        try:
            # Check if there's an availability record for this time
            availability_query = select(Availability).where(
                and_(
                    Availability.tutor_id == tutor_id,
                    Availability.status == AvailabilityStatus.AVAILABLE,
                    Availability.start_time <= start_time,
                    Availability.end_time >= end_time
                )
            )
            
            result = await db.execute(availability_query)
            availability = result.scalar_one_or_none()
            
            if not availability:
                return False
            
            # Check if there are any existing bookings for this time
            booking_query = select(Booking).where(
                and_(
                    Booking.tutor_id == tutor_id,
                    Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING]),
                    or_(
                        and_(
                            Booking.start_time < end_time,
                            Booking.end_time > start_time
                        )
                    )
                )
            )
            
            result = await db.execute(booking_query)
            existing_booking = result.scalar_one_or_none()
            
            return existing_booking is None
            
        except Exception as e:
            raise AvailabilityError(f"Failed to check slot availability: {str(e)}")
    
    async def mark_slot_held(
        self,
        tutor_id: str,
        start_time: datetime,
        end_time: datetime,
        hold_id: str,
        db: AsyncSession
    ):
        """Mark a slot as held temporarily"""
        try:
            # Create a temporary availability record for the hold
            held_slot = Availability(
                id=uuid.uuid4(),
                tutor_id=tutor_id,
                start_time=start_time,
                end_time=end_time,
                status=AvailabilityStatus.HELD,
                recurring_rule=None,
                metadata={"hold_id": hold_id},
                created_at=datetime.now(timezone.utc)
            )
            
            db.add(held_slot)
            await db.commit()
            
        except Exception as e:
            await db.rollback()
            raise AvailabilityError(f"Failed to mark slot as held: {str(e)}")
    
    async def release_held_slot(
        self,
        tutor_id: str,
        start_time: datetime,
        end_time: datetime,
        db: AsyncSession
    ):
        """Release a held slot"""
        try:
            # Remove held availability records
            query = select(Availability).where(
                and_(
                    Availability.tutor_id == tutor_id,
                    Availability.status == AvailabilityStatus.HELD,
                    Availability.start_time == start_time,
                    Availability.end_time == end_time
                )
            )
            
            result = await db.execute(query)
            held_slots = result.scalars().all()
            
            for slot in held_slots:
                await db.delete(slot)
            
            await db.commit()
            
        except Exception as e:
            await db.rollback()
            raise AvailabilityError(f"Failed to release held slot: {str(e)}")
    
    def filter_busy_times(
        self,
        availability: List[Dict[str, Any]],
        busy_times: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Filter out busy times from availability"""
        filtered_availability = []
        
        for slot in availability:
            slot_start = datetime.fromisoformat(slot["start_time"])
            slot_end = datetime.fromisoformat(slot["end_time"])
            
            is_available = True
            for busy_time in busy_times:
                busy_start = datetime.fromisoformat(busy_time["start"])
                busy_end = datetime.fromisoformat(busy_time["end"])
                
                # Check if there's any overlap
                if slot_start < busy_end and slot_end > busy_start:
                    is_available = False
                    break
            
            if is_available:
                filtered_availability.append(slot)
        
        return filtered_availability
    
    async def create_recurring_availability(
        self,
        tutor_id: str,
        start_time: datetime,
        end_time: datetime,
        recurring_rule: str,
        db: AsyncSession
    ):
        """Create recurring availability using RRULE"""
        try:
            from dateutil import rrule
            
            # Parse RRULE and generate occurrences
            rule = rrule.rrulestr(recurring_rule, dtstart=start_time)
            
            # Generate availability for next 30 days
            end_date = datetime.now(timezone.utc) + timedelta(days=30)
            
            for occurrence in rule.between(
                datetime.now(timezone.utc),
                end_date
            ):
                availability = Availability(
                    id=uuid.uuid4(),
                    tutor_id=tutor_id,
                    start_time=occurrence,
                    end_time=occurrence + (end_time - start_time),
                    status=AvailabilityStatus.AVAILABLE,
                    recurring_rule=recurring_rule,
                    created_at=datetime.now(timezone.utc)
                )
                
                db.add(availability)
            
            await db.commit()
            
        except Exception as e:
            await db.rollback()
            raise AvailabilityError(f"Failed to create recurring availability: {str(e)}")
    
    async def create_timeoff(
        self,
        tutor_id: str,
        start_time: datetime,
        end_time: datetime,
        reason: str,
        db: AsyncSession
    ):
        """Create timeoff/blackout period"""
        try:
            timeoff = Availability(
                id=uuid.uuid4(),
                tutor_id=tutor_id,
                start_time=start_time,
                end_time=end_time,
                status=AvailabilityStatus.UNAVAILABLE,
                recurring_rule=None,
                metadata={"reason": reason, "type": "timeoff"},
                created_at=datetime.now(timezone.utc)
            )
            
            db.add(timeoff)
            await db.commit()
            
        except Exception as e:
            await db.rollback()
            raise AvailabilityError(f"Failed to create timeoff: {str(e)}")
