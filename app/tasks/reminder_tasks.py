from datetime import datetime, timedelta, timezone
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.models.booking import Booking, BookingStatus
from app.services.notification_service import NotificationService
from app.services.scheduling_service import SchedulingService

logger = logging.getLogger(__name__)


async def send_booking_reminders():
    """Background task to send booking reminders (24h and 2h before session)"""
    async with AsyncSessionLocal() as db:
        try:
            notification_service = NotificationService(db)
            await notification_service.send_booking_reminders()
            logger.info("Booking reminders sent successfully")
        except Exception as e:
            logger.error(f"Error sending booking reminders: {e}")


async def cleanup_expired_holds():
    """Background task to cleanup expired slot holds"""
    async with AsyncSessionLocal() as db:
        try:
            from app.models.availability import Slot, SlotStatus
            
            # Find held slots that have expired (more than 10 minutes old)
            expired_time = datetime.now(timezone.utc) - timedelta(minutes=10)
            
            expired_slots = await db.execute(
                select(Slot).where(
                    and_(
                        Slot.status == SlotStatus.HELD,
                        Slot.updated_at < expired_time,
                        Slot.deleted_at.is_(None)
                    )
                )
            ).scalars().all()
            
            # Release expired slots
            for slot in expired_slots:
                slot.status = SlotStatus.OPEN
                slot.updated_at = datetime.now(timezone.utc)
            
            await db.commit()
            
            if expired_slots:
                logger.info(f"Released {len(expired_slots)} expired slot holds")
            
        except Exception as e:
            logger.error(f"Error cleaning up expired holds: {e}")


async def generate_future_slots():
    """Background task to generate future slots from recurring availability"""
    async with AsyncSessionLocal() as db:
        try:
            from app.models.availability import AvailabilityBlock
            
            # Get recurring availability blocks
            recurring_blocks = await db.execute(
                select(AvailabilityBlock).where(
                    and_(
                        AvailabilityBlock.is_recurring == True,
                        AvailabilityBlock.deleted_at.is_(None)
                    )
                )
            ).scalars().all()
            
            scheduling_service = SchedulingService(db)
            
            for block in recurring_blocks:
                try:
                    # Generate slots for the next 8 weeks
                    await scheduling_service._generate_slots_from_availability(block)
                except Exception as e:
                    logger.error(f"Error generating slots for availability block {block.id}: {e}")
            
            logger.info(f"Generated future slots for {len(recurring_blocks)} recurring availability blocks")
            
        except Exception as e:
            logger.error(f"Error generating future slots: {e}")


async def sync_google_calendar_events():
    """Background task to sync Google Calendar events and update availability"""
    async with AsyncSessionLocal() as db:
        try:
            from app.models.google_oauth import GoogleOAuthAccount
            from app.models.availability import Slot, SlotStatus
            from app.services.google_calendar_service import GoogleCalendarService
            
            # Get all connected Google Calendar accounts
            oauth_accounts = await db.execute(
                select(GoogleOAuthAccount).where(
                    and_(
                        GoogleOAuthAccount.deleted_at.is_(None)
                    )
                )
            ).scalars().all()
            
            google_calendar = GoogleCalendarService()
            
            for oauth_account in oauth_accounts:
                try:
                    # Get busy times for the next 2 weeks
                    start_date = datetime.now(timezone.utc)
                    end_date = start_date + timedelta(weeks=2)
                    
                    busy_times = await google_calendar.get_busy_times(
                        access_token=oauth_account.access_token,
                        start_date=start_date,
                        end_date=end_date
                    )
                    
                    # Get open slots for this user
                    open_slots = await db.execute(
                        select(Slot).where(
                            and_(
                                Slot.tutor_id == oauth_account.user_id,
                                Slot.status == SlotStatus.OPEN,
                                Slot.start_at >= start_date,
                                Slot.start_at <= end_date,
                                Slot.deleted_at.is_(None)
                            )
                        )
                    ).scalars().all()
                    
                    # Check for conflicts and close conflicting slots
                    for slot in open_slots:
                        for busy_time in busy_times:
                            busy_start = datetime.fromisoformat(busy_time["start"].replace('Z', '+00:00'))
                            busy_end = datetime.fromisoformat(busy_time["end"].replace('Z', '+00:00'))
                            
                            # Check for overlap
                            if (slot.start_at < busy_end and slot.end_at > busy_start):
                                slot.status = SlotStatus.CLOSED
                                slot.updated_at = datetime.now(timezone.utc)
                                break
                    
                    await db.commit()
                    
                except Exception as e:
                    logger.error(f"Error syncing calendar for user {oauth_account.user_id}: {e}")
            
            logger.info(f"Synced Google Calendar events for {len(oauth_accounts)} users")
            
        except Exception as e:
            logger.error(f"Error syncing Google Calendar events: {e}")


async def process_no_show_bookings():
    """Background task to process no-show bookings"""
    async with AsyncSessionLocal() as db:
        try:
            # Find completed bookings that are past their end time
            now = datetime.now(timezone.utc)
            
            completed_bookings = await db.execute(
                select(Booking).where(
                    and_(
                        Booking.status == BookingStatus.CONFIRMED,
                        Booking.end_at < now,
                        Booking.deleted_at.is_(None)
                    )
                )
            ).scalars().all()
            
            for booking in completed_bookings:
                try:
                    # Mark booking as completed
                    booking.status = BookingStatus.COMPLETED
                    booking.notes = f"{booking.notes or ''}\nMarked as completed automatically"
                    booking.updated_at = datetime.now(timezone.utc)
                    
                    # Send completion notification
                    notification_service = NotificationService(db)
                    await notification_service.send_booking_completion_notification(booking)
                    
                except Exception as e:
                    logger.error(f"Error processing no-show booking {booking.id}: {e}")
            
            await db.commit()
            
            if completed_bookings:
                logger.info(f"Processed {len(completed_bookings)} completed bookings")
            
        except Exception as e:
            logger.error(f"Error processing no-show bookings: {e}")


async def cleanup_old_slots():
    """Background task to cleanup old slots (older than 3 months)"""
    async with AsyncSessionLocal() as db:
        try:
            from app.models.availability import Slot
            
            # Find slots older than 3 months
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)
            
            old_slots = await db.execute(
                select(Slot).where(
                    and_(
                        Slot.start_at < cutoff_date,
                        Slot.deleted_at.is_(None)
                    )
                )
            ).scalars().all()
            
            # Soft delete old slots
            for slot in old_slots:
                slot.deleted_at = datetime.now(timezone.utc)
            
            await db.commit()
            
            if old_slots:
                logger.info(f"Cleaned up {len(old_slots)} old slots")
            
        except Exception as e:
            logger.error(f"Error cleaning up old slots: {e}")


# Task scheduler functions
async def schedule_reminder_tasks():
    """Schedule all reminder-related background tasks"""
    while True:
        try:
            # Send booking reminders every hour
            await send_booking_reminders()
            
            # Cleanup expired holds every 5 minutes
            await cleanup_expired_holds()
            
            # Generate future slots daily at 2 AM
            now = datetime.now(timezone.utc)
            if now.hour == 2 and now.minute < 5:
                await generate_future_slots()
            
            # Sync Google Calendar events every 30 minutes
            if now.minute % 30 < 5:
                await sync_google_calendar_events()
            
            # Process no-show bookings every 15 minutes
            if now.minute % 15 < 5:
                await process_no_show_bookings()
            
            # Cleanup old slots daily at 3 AM
            if now.hour == 3 and now.minute < 5:
                await cleanup_old_slots()
            
            # Wait for 5 minutes before next iteration
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"Error in reminder task scheduler: {e}")
            await asyncio.sleep(60)  # Wait 1 minute on error


# Celery task definitions (if using Celery)
def send_booking_reminders_task():
    """Celery task wrapper for sending booking reminders"""
    asyncio.run(send_booking_reminders())


def cleanup_expired_holds_task():
    """Celery task wrapper for cleaning up expired holds"""
    asyncio.run(cleanup_expired_holds())


def generate_future_slots_task():
    """Celery task wrapper for generating future slots"""
    asyncio.run(generate_future_slots())


def sync_google_calendar_events_task():
    """Celery task wrapper for syncing Google Calendar events"""
    asyncio.run(sync_google_calendar_events_task())


def process_no_show_bookings_task():
    """Celery task wrapper for processing no-show bookings"""
    asyncio.run(process_no_show_bookings())


def cleanup_old_slots_task():
    """Celery task wrapper for cleaning up old slots"""
    asyncio.run(cleanup_old_slots())
