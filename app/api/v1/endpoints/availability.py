from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/tutors/{tutor_id}")
async def get_tutor_availability(
    tutor_id: int,
    date: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Get tutor availability"""
    pass


@router.post("/tutors/{tutor_id}/book")
async def book_session(
    tutor_id: int,
    start_time: str,
    duration: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Book a session with tutor"""
    pass


@router.get("/my-availability")
async def get_my_availability(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get current user's availability (for tutors)"""
    pass


@router.post("/my-availability")
async def set_availability(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Set availability (for tutors)"""
    pass
