from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import uuid

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.models.booking import Booking
from app.services.calendar_service import CalendarService
from app.services.google_oauth_service import GoogleOAuthService
from app.core.exceptions import GoogleCalendarError, OAuthError

router = APIRouter()


@router.get("/calendar/status")
async def get_calendar_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get calendar connection status and primary calendar ID"""
    try:
        return {
            "connected": bool(current_user.google_calendar_id),
            "primary_calendar_id": current_user.google_calendar_id,
            "calendar_name": current_user.google_calendar_name,
            "last_sync": current_user.google_calendar_last_sync.isoformat() if current_user.google_calendar_last_sync else None
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get calendar status: {str(e)}"
        )


@router.get("/calendar/connect-url")
async def get_calendar_connect_url(
    current_user: User = Depends(get_current_user)
):
    """Get Google OAuth authorization URL"""
    try:
        google_oauth_service = GoogleOAuthService()
        auth_url = google_oauth_service.get_authorization_url(str(current_user.id))
        
        return {
            "auth_url": auth_url,
            "state": str(current_user.id)  # For verification
        }
        
    except OAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate auth URL: {str(e)}"
        )


@router.post("/google/oauth/callback")
async def google_oauth_callback(
    code: str = Body(..., embed=True),
    state: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Handle Google OAuth callback and token exchange"""
    try:
        # Verify state matches current user
        if state != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid state parameter"
            )
        
        google_oauth_service = GoogleOAuthService()
        
        # Exchange code for tokens
        tokens = await google_oauth_service.exchange_code_for_tokens(code)
        
        # Get user's primary calendar
        calendar_service = CalendarService()
        primary_calendar = await calendar_service.get_primary_calendar(tokens["access_token"])
        
        # Update user with calendar info
        current_user.google_access_token = tokens["access_token"]
        current_user.google_refresh_token = tokens["refresh_token"]
        current_user.google_calendar_id = primary_calendar["id"]
        current_user.google_calendar_name = primary_calendar["summary"]
        current_user.google_calendar_last_sync = datetime.now(timezone.utc)
        
        db.add(current_user)
        await db.commit()
        await db.refresh(current_user)
        
        return {
            "success": True,
            "calendar_id": primary_calendar["id"],
            "calendar_name": primary_calendar["summary"],
            "connected_at": current_user.google_calendar_last_sync.isoformat()
        }
        
    except OAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except GoogleCalendarError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except OAuthError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except GoogleCalendarError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to complete OAuth: {str(e)}"
        )


@router.post("/calendar/sync/{booking_id}")
async def sync_booking_calendar(
    booking_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """(Re)create calendar events for a booking"""
    try:
        # Get booking
        result = await db.execute(
            select(Booking).where(Booking.id == booking_id)
        )
        booking = result.scalar_one_or_none()
        
        if not booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found"
            )
        
        # Check if user is authorized to sync this booking
        if booking.student_id != current_user.id and booking.tutor_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to sync this booking"
            )
        
        # Check if user has connected calendar
        if not current_user.google_calendar_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Calendar not connected"
            )
        
        calendar_service = CalendarService()
        
        # Create or update calendar events
        if booking.status.value in ["confirmed", "rescheduled"]:
            event_result = await calendar_service.create_or_update_booking_event(
                booking,
                current_user,
                db
            )
            
            return {
                "success": True,
                "event_id": event_result["event_id"],
                "calendar_id": current_user.google_calendar_id,
                "synced_at": datetime.now(timezone.utc).isoformat()
            }
        else:
            # Cancel events for cancelled bookings
            await calendar_service.cancel_booking_events(booking, db)
            
            return {
                "success": True,
                "event_cancelled": True,
                "synced_at": datetime.now(timezone.utc).isoformat()
            }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync calendar: {str(e)}"
        )


@router.post("/calendar/disconnect")
async def disconnect_calendar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Disconnect Google Calendar"""
    try:
        # Clear calendar connection
        current_user.google_access_token = None
        current_user.google_refresh_token = None
        current_user.google_calendar_id = None
        current_user.google_calendar_name = None
        current_user.google_calendar_last_sync = None
        
        db.add(current_user)
        await db.commit()
        await db.refresh(current_user)
        
        return {
            "success": True,
            "disconnected_at": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect calendar: {str(e)}"
        )


@router.get("/calendar/events")
async def get_calendar_events(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get calendar events for the connected calendar"""
    try:
        if not current_user.google_calendar_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Calendar not connected"
            )
        
        calendar_service = CalendarService()
        events = await calendar_service.get_calendar_events(
            current_user,
            start_date,
            end_date
        )
        
        return {
            "events": events,
            "calendar_id": current_user.google_calendar_id,
            "calendar_name": current_user.google_calendar_name
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch calendar events: {str(e)}"
        )
