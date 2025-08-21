from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import json

from app.models.booking import Booking
from app.models.user import User
from app.models.notification import Notification, NotificationType, NotificationDelivery, NotificationStatus
from app.models.tutor_profile import TutorProfile
from app.models.student_profile import StudentProfile
from app.services.email_service import EmailService
from app.services.sms_service import SMSService
from app.core.config import settings


class NotificationService:
    """Comprehensive notification service for booking and system notifications"""
    
    def __init__(self, db: AsyncSession = None):
        self.db = db
        self.email_service = EmailService()
        self.sms_service = SMSService()
    
    async def send_booking_confirmation_email(self, booking: Booking) -> None:
        """Send booking confirmation email to both tutor and student"""
        try:
            # Get user details
            tutor = await self._get_user_details(booking.tutor_id)
            student = await self._get_user_details(booking.student_id)
            
            if not tutor or not student:
                return
            
            # Email to student
            await self.email_service.send_booking_confirmation_student(
                to_email=student.email,
                student_name=student.name,
                tutor_name=tutor.name,
                start_time=booking.start_at,
                end_time=booking.end_at,
                subject="Tutoring Session Confirmed",
                join_link=booking.join_link
            )
            
            # Email to tutor
            await self.email_service.send_booking_confirmation_tutor(
                to_email=tutor.email,
                tutor_name=tutor.name,
                student_name=student.name,
                start_time=booking.start_at,
                end_time=booking.end_at,
                subject="New Tutoring Session Booked"
            )
            
        except Exception as e:
            print(f"Error sending booking confirmation email: {e}")
    
    async def send_booking_confirmation_notification(self, booking: Booking) -> None:
        """Send in-app booking confirmation notification"""
        try:
            # Create notification for student
            student_notification = Notification(
                user_id=booking.student_id,
                type=NotificationType.BOOKING_CONFIRMATION,
                payload=json.dumps({
                    "booking_id": str(booking.id),
                    "tutor_name": await self._get_user_name(booking.tutor_id),
                    "start_time": booking.start_at.isoformat(),
                    "end_time": booking.end_at.isoformat(),
                    "join_link": booking.join_link
                }),
                delivery=NotificationDelivery.INAPP,
                status=NotificationStatus.PENDING
            )
            
            # Create notification for tutor
            tutor_notification = Notification(
                user_id=booking.tutor_id,
                type=NotificationType.BOOKING_CONFIRMATION,
                payload=json.dumps({
                    "booking_id": str(booking.id),
                    "student_name": await self._get_user_name(booking.student_id),
                    "start_time": booking.start_at.isoformat(),
                    "end_time": booking.end_at.isoformat()
                }),
                delivery=NotificationDelivery.INAPP,
                status=NotificationStatus.PENDING
            )
            
            if self.db:
                self.db.add(student_notification)
                self.db.add(tutor_notification)
                await self.db.commit()
            
        except Exception as e:
            print(f"Error sending booking confirmation notification: {e}")
    
    async def send_booking_cancellation_notification(self, booking: Booking) -> None:
        """Send booking cancellation notification"""
        try:
            # Get user details
            tutor = await self._get_user_details(booking.tutor_id)
            student = await self._get_user_details(booking.student_id)
            
            if not tutor or not student:
                return
            
            # Email to student
            await self.email_service.send_booking_cancellation_student(
                to_email=student.email,
                student_name=student.name,
                tutor_name=tutor.name,
                start_time=booking.start_at,
                end_time=booking.end_at,
                subject="Tutoring Session Cancelled"
            )
            
            # Email to tutor
            await self.email_service.send_booking_cancellation_tutor(
                to_email=tutor.email,
                tutor_name=tutor.name,
                student_name=student.name,
                start_time=booking.start_at,
                end_time=booking.end_at,
                subject="Tutoring Session Cancelled"
            )
            
            # In-app notifications
            await self._create_inapp_notification(
                user_id=booking.student_id,
                notification_type=NotificationType.BOOKING_CANCELLATION,
                payload={
                    "booking_id": str(booking.id),
                    "tutor_name": tutor.name,
                    "start_time": booking.start_at.isoformat(),
                    "end_time": booking.end_at.isoformat()
                }
            )
            
            await self._create_inapp_notification(
                user_id=booking.tutor_id,
                notification_type=NotificationType.BOOKING_CANCELLATION,
                payload={
                    "booking_id": str(booking.id),
                    "student_name": student.name,
                    "start_time": booking.start_at.isoformat(),
                    "end_time": booking.end_at.isoformat()
                }
            )
            
        except Exception as e:
            print(f"Error sending booking cancellation notification: {e}")
    
    async def send_booking_reschedule_notification(
        self,
        new_booking: Booking,
        old_booking: Booking
    ) -> None:
        """Send booking reschedule notification"""
        try:
            # Get user details
            tutor = await self._get_user_details(new_booking.tutor_id)
            student = await self._get_user_details(new_booking.student_id)
            
            if not tutor or not student:
                return
            
            # Email to student
            await self.email_service.send_booking_reschedule_student(
                to_email=student.email,
                student_name=student.name,
                tutor_name=tutor.name,
                old_start_time=old_booking.start_at,
                old_end_time=old_booking.end_at,
                new_start_time=new_booking.start_at,
                new_end_time=new_booking.end_at,
                subject="Tutoring Session Rescheduled"
            )
            
            # Email to tutor
            await self.email_service.send_booking_reschedule_tutor(
                to_email=tutor.email,
                tutor_name=tutor.name,
                student_name=student.name,
                old_start_time=old_booking.start_at,
                old_end_time=old_booking.end_at,
                new_start_time=new_booking.start_at,
                new_end_time=new_booking.end_at,
                subject="Tutoring Session Rescheduled"
            )
            
            # In-app notifications
            await self._create_inapp_notification(
                user_id=new_booking.student_id,
                notification_type=NotificationType.BOOKING_CONFIRMATION,
                payload={
                    "booking_id": str(new_booking.id),
                    "tutor_name": tutor.name,
                    "start_time": new_booking.start_at.isoformat(),
                    "end_time": new_booking.end_at.isoformat(),
                    "rescheduled": True
                }
            )
            
            await self._create_inapp_notification(
                user_id=new_booking.tutor_id,
                notification_type=NotificationType.BOOKING_CONFIRMATION,
                payload={
                    "booking_id": str(new_booking.id),
                    "student_name": student.name,
                    "start_time": new_booking.start_at.isoformat(),
                    "end_time": new_booking.end_at.isoformat(),
                    "rescheduled": True
                }
            )
            
        except Exception as e:
            print(f"Error sending booking reschedule notification: {e}")
    
    async def send_booking_reminders(self) -> None:
        """Send booking reminders (24h and 2h before session)"""
        try:
            # Get upcoming bookings
            now = datetime.now(timezone.utc)
            tomorrow = now + timedelta(days=1)
            two_hours_from_now = now + timedelta(hours=2)
            
            # 24-hour reminders
            bookings_24h = await self._get_upcoming_bookings(
                start_time=now,
                end_time=tomorrow,
                reminder_sent_24h=False
            )
            
            for booking in bookings_24h:
                await self._send_reminder_notification(booking, "24h")
                # Mark 24h reminder as sent (you'd need to add this field to booking model)
            
            # 2-hour reminders
            bookings_2h = await self._get_upcoming_bookings(
                start_time=now,
                end_time=two_hours_from_now,
                reminder_sent_2h=False
            )
            
            for booking in bookings_2h:
                await self._send_reminder_notification(booking, "2h")
                # Mark 2h reminder as sent
            
        except Exception as e:
            print(f"Error sending booking reminders: {e}")
    
    async def _send_reminder_notification(self, booking: Booking, reminder_type: str) -> None:
        """Send reminder notification for a booking"""
        try:
            tutor = await self._get_user_details(booking.tutor_id)
            student = await self._get_user_details(booking.student_id)
            
            if not tutor or not student:
                return
            
            # Email reminders
            await self.email_service.send_booking_reminder_student(
                to_email=student.email,
                student_name=student.name,
                tutor_name=tutor.name,
                start_time=booking.start_at,
                end_time=booking.end_at,
                reminder_type=reminder_type,
                join_link=booking.join_link
            )
            
            await self.email_service.send_booking_reminder_tutor(
                to_email=tutor.email,
                tutor_name=tutor.name,
                student_name=student.name,
                start_time=booking.start_at,
                end_time=booking.end_at,
                reminder_type=reminder_type
            )
            
            # SMS reminders (if opted in)
            await self._send_sms_reminder(student, booking, reminder_type)
            await self._send_sms_reminder(tutor, booking, reminder_type)
            
            # In-app notifications
            await self._create_inapp_notification(
                user_id=booking.student_id,
                notification_type=NotificationType.BOOKING_REMINDER,
                payload={
                    "booking_id": str(booking.id),
                    "tutor_name": tutor.name,
                    "start_time": booking.start_at.isoformat(),
                    "end_time": booking.end_at.isoformat(),
                    "reminder_type": reminder_type,
                    "join_link": booking.join_link
                }
            )
            
            await self._create_inapp_notification(
                user_id=booking.tutor_id,
                notification_type=NotificationType.BOOKING_REMINDER,
                payload={
                    "booking_id": str(booking.id),
                    "student_name": student.name,
                    "start_time": booking.start_at.isoformat(),
                    "end_time": booking.end_at.isoformat(),
                    "reminder_type": reminder_type
                }
            )
            
        except Exception as e:
            print(f"Error sending reminder notification: {e}")
    
    async def _send_sms_reminder(self, user: User, booking: Booking, reminder_type: str) -> None:
        """Send SMS reminder (if user has opted in)"""
        try:
            # Check if user has opted in for SMS notifications
            # This would be stored in user preferences
            sms_opted_in = True  # Placeholder - implement user preference check
            
            if sms_opted_in and user.phone_number:
                message = f"Reminder: Your tutoring session is in {reminder_type}. "
                if reminder_type == "2h":
                    message += f"Join at: {booking.join_link}"
                
                await self.sms_service.send_sms(
                    phone_number=user.phone_number,
                    message=message
                )
        except Exception as e:
            print(f"Error sending SMS reminder: {e}")
    
    async def send_payment_success_notification(self, payment: Any) -> None:
        """Send payment success notification"""
        try:
            user = await self._get_user_details(payment.user_id)
            if not user:
                return
            
            await self.email_service.send_payment_success(
                to_email=user.email,
                user_name=user.name,
                amount=payment.amount_cents / 100,  # Convert cents to dollars
                payment_type=payment.type.value
            )
            
            await self._create_inapp_notification(
                user_id=payment.user_id,
                notification_type=NotificationType.PAYMENT_SUCCESS,
                payload={
                    "payment_id": str(payment.id),
                    "amount": payment.amount_cents,
                    "payment_type": payment.type.value
                }
            )
            
        except Exception as e:
            print(f"Error sending payment success notification: {e}")
    
    async def send_payment_failed_notification(self, payment: Any) -> None:
        """Send payment failed notification"""
        try:
            user = await self._get_user_details(payment.user_id)
            if not user:
                return
            
            await self.email_service.send_payment_failed(
                to_email=user.email,
                user_name=user.name,
                amount=payment.amount_cents / 100,
                payment_type=payment.type.value
            )
            
            await self._create_inapp_notification(
                user_id=payment.user_id,
                notification_type=NotificationType.PAYMENT_FAILED,
                payload={
                    "payment_id": str(payment.id),
                    "amount": payment.amount_cents,
                    "payment_type": payment.type.value
                }
            )
            
        except Exception as e:
            print(f"Error sending payment failed notification: {e}")
    
    async def send_credit_low_notification(self, user_id: str, current_balance: int) -> None:
        """Send low credit balance notification"""
        try:
            user = await self._get_user_details(user_id)
            if not user:
                return
            
            await self.email_service.send_credit_low(
                to_email=user.email,
                user_name=user.name,
                current_balance=current_balance
            )
            
            await self._create_inapp_notification(
                user_id=user_id,
                notification_type=NotificationType.CREDIT_LOW,
                payload={
                    "current_balance": current_balance
                }
            )
            
        except Exception as e:
            print(f"Error sending credit low notification: {e}")
    
    async def send_ai_artifact_ready_notification(self, artifact: Any) -> None:
        """Send notification when AI artifact is ready"""
        try:
            user = await self._get_user_details(artifact.user_id)
            if not user:
                return
            
            await self.email_service.send_ai_artifact_ready(
                to_email=user.email,
                user_name=user.name,
                artifact_type=artifact.type.value
            )
            
            await self._create_inapp_notification(
                user_id=artifact.user_id,
                notification_type=NotificationType.AI_ARTIFACT_READY,
                payload={
                    "artifact_id": str(artifact.id),
                    "artifact_type": artifact.type.value
                }
            )
            
        except Exception as e:
            print(f"Error sending AI artifact ready notification: {e}")
    
    async def _get_user_details(self, user_id: str) -> Optional[User]:
        """Get user details from database"""
        if not self.db:
            return None
        
        try:
            user = await self.db.execute(
                select(User).where(
                    and_(
                        User.id == user_id,
                        User.deleted_at.is_(None)
                    )
                )
            ).scalar_one_or_none()
            
            return user
        except Exception as e:
            print(f"Error getting user details: {e}")
            return None
    
    async def _get_user_name(self, user_id: str) -> str:
        """Get user name from database"""
        user = await self._get_user_details(user_id)
        return user.name if user else "Unknown User"
    
    async def _get_upcoming_bookings(
        self,
        start_time: datetime,
        end_time: datetime,
        reminder_sent_24h: bool = None,
        reminder_sent_2h: bool = None
    ) -> List[Booking]:
        """Get upcoming bookings for reminders"""
        if not self.db:
            return []
        
        try:
            query = select(Booking).where(
                and_(
                    Booking.start_at >= start_time,
                    Booking.start_at <= end_time,
                    Booking.status == "confirmed",
                    Booking.deleted_at.is_(None)
                )
            )
            
            # Add reminder filters if provided
            # Note: You'd need to add these fields to the booking model
            # if reminder_sent_24h is not None:
            #     query = query.where(Booking.reminder_sent_24h == reminder_sent_24h)
            # if reminder_sent_2h is not None:
            #     query = query.where(Booking.reminder_sent_2h == reminder_sent_2h)
            
            bookings = await self.db.execute(query)
            return bookings.scalars().all()
            
        except Exception as e:
            print(f"Error getting upcoming bookings: {e}")
            return []
    
    async def _create_inapp_notification(
        self,
        user_id: str,
        notification_type: NotificationType,
        payload: Dict[str, Any]
    ) -> None:
        """Create in-app notification"""
        if not self.db:
            return
        
        try:
            notification = Notification(
                user_id=user_id,
                type=notification_type,
                payload=json.dumps(payload),
                delivery=NotificationDelivery.INAPP,
                status=NotificationStatus.PENDING
            )
            
            self.db.add(notification)
            await self.db.commit()
            
        except Exception as e:
            print(f"Error creating in-app notification: {e}")
    
    async def mark_notification_as_read(self, notification_id: str, user_id: str) -> bool:
        """Mark notification as read"""
        if not self.db:
            return False
        
        try:
            notification = await self.db.execute(
                select(Notification).where(
                    and_(
                        Notification.id == notification_id,
                        Notification.user_id == user_id,
                        Notification.deleted_at.is_(None)
                    )
                )
            ).scalar_one_or_none()
            
            if notification:
                notification.status = NotificationStatus.READ
                await self.db.commit()
                return True
            
            return False
            
        except Exception as e:
            print(f"Error marking notification as read: {e}")
            return False
    
    async def get_user_notifications(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False
    ) -> List[Notification]:
        """Get user notifications"""
        if not self.db:
            return []
        
        try:
            query = select(Notification).where(
                and_(
                    Notification.user_id == user_id,
                    Notification.deleted_at.is_(None)
                )
            )
            
            if unread_only:
                query = query.where(Notification.status == NotificationStatus.PENDING)
            
            query = query.order_by(Notification.created_at.desc())
            query = query.offset(offset).limit(limit)
            
            notifications = await self.db.execute(query)
            return notifications.scalars().all()
            
        except Exception as e:
            print(f"Error getting user notifications: {e}")
            return []
