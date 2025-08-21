from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User, UserRole
from app.models.tutor_profile import TutorProfile
from app.models.availability import AvailabilityBlock
from app.schemas.tutor import TutorListResponse, TutorDetailResponse, TutorSearchParams

router = APIRouter()


@router.get("/tutors", response_model=List[TutorListResponse])
async def list_tutors(
    search: Optional[str] = Query(None, description="Search by name or subject"),
    subject: Optional[str] = Query(None, description="Filter by subject"),
    min_rating: Optional[float] = Query(None, description="Minimum rating"),
    max_rate: Optional[int] = Query(None, description="Maximum hourly rate in cents"),
    available_after: Optional[datetime] = Query(None, description="Available after this time"),
    limit: int = Query(20, ge=1, le=100, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    db: AsyncSession = Depends(get_db)
):
    """List/search tutors with filters"""
    try:
        # Build query
        query = select(TutorProfile).join(User).where(User.role == UserRole.TUTOR)
        
        # Apply filters
        if search:
            search_filter = or_(
                User.first_name.ilike(f"%{search}%"),
                User.last_name.ilike(f"%{search}%"),
                TutorProfile.subjects.any(lambda x: x.ilike(f"%{search}%")),
                TutorProfile.bio.ilike(f"%{search}%")
            )
            query = query.where(search_filter)
        
        if subject:
            query = query.where(TutorProfile.subjects.any(lambda x: x.ilike(f"%{subject}%")))
        
        if min_rating:
            query = query.where(TutorProfile.average_rating >= min_rating)
        
        if max_rate:
            query = query.where(TutorProfile.hourly_rate_cents <= max_rate)
        
        # Apply availability filter if specified
        if available_after:
            # This would need to be implemented with availability checking
            # For now, we'll just filter active tutors
            query = query.where(TutorProfile.is_active == True)
        
        # Apply pagination
        query = query.offset(offset).limit(limit)
        
        # Execute query
        result = await db.execute(query)
        tutors = result.scalars().all()
        
        # Convert to response format
        tutor_responses = []
        for tutor in tutors:
            tutor_responses.append({
                "id": str(tutor.user_id),
                "name": f"{tutor.user.first_name} {tutor.user.last_name}",
                "subjects": tutor.subjects,
                "hourly_rate_cents": tutor.hourly_rate_cents,
                "average_rating": tutor.average_rating,
                "total_sessions": tutor.total_sessions,
                "bio": tutor.bio,
                "is_active": tutor.is_active,
                "profile_image_url": tutor.profile_image_url
            })
        
        return tutor_responses
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch tutors: {str(e)}"
        )


@router.get("/tutors/{tutor_id}", response_model=TutorDetailResponse)
async def get_tutor_profile(
    tutor_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get detailed tutor profile"""
    try:
        # Get tutor profile with user info
        result = await db.execute(
            select(TutorProfile)
            .join(User)
            .where(and_(
                TutorProfile.user_id == tutor_id,
                User.role == UserRole.TUTOR
            ))
        )
        tutor = result.scalar_one_or_none()
        
        if not tutor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tutor not found"
            )
        
        # Get availability for next 7 days
        from app.services.availability_service import AvailabilityService
        availability_service = AvailabilityService()
        availability = await availability_service.get_tutor_availability(
            tutor_id, 
            days_ahead=7,
            db=db
        )
        
        return {
            "id": str(tutor.user_id),
            "name": f"{tutor.user.first_name} {tutor.user.last_name}",
            "email": tutor.user.email,
            "subjects": tutor.subjects,
            "hourly_rate_cents": tutor.hourly_rate_cents,
            "average_rating": tutor.average_rating,
            "total_sessions": tutor.total_sessions,
            "total_students": tutor.total_students,
            "bio": tutor.bio,
            "education": tutor.education,
            "experience_years": tutor.experience_years,
            "is_active": tutor.is_active,
            "profile_image_url": tutor.profile_image_url,
            "availability": availability,
            "reviews": [],  # TODO: Implement reviews
            "certifications": tutor.certifications or []
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch tutor profile: {str(e)}"
        )


@router.get("/tutors/{tutor_id}/slots")
async def get_tutor_slots(
    tutor_id: str,
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    timezone: str = Query("UTC", description="User's timezone"),
    db: AsyncSession = Depends(get_db)
):
    """Get tutor's available slots (timezone-aware, includes Google busy)"""
    try:
        from app.services.availability_service import AvailabilityService
        from app.services.calendar_service import CalendarService
        
        availability_service = AvailabilityService()
        calendar_service = CalendarService()
        
        # Parse date
        target_date = None
        if date:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid date format. Use YYYY-MM-DD"
                )
        
        # Get tutor's availability
        availability = await availability_service.get_tutor_availability(
            tutor_id,
            target_date=target_date,
            timezone=timezone,
            db=db
        )
        
        # Get Google Calendar busy times
        tutor = await db.execute(
            select(User).where(User.id == tutor_id)
        )
        tutor_user = tutor.scalar_one_or_none()
        
        if tutor_user and tutor_user.google_calendar_id:
            busy_times = await calendar_service.get_busy_times(
                tutor_user.google_calendar_id,
                target_date,
                timezone
            )
            
            # Filter out busy times from availability
            available_slots = availability_service.filter_busy_times(
                availability, 
                busy_times
            )
        else:
            available_slots = availability
        
        return {
            "tutor_id": tutor_id,
            "date": date,
            "timezone": timezone,
            "available_slots": available_slots,
            "slot_duration_minutes": 60  # Default slot duration
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch tutor slots: {str(e)}"
        )
