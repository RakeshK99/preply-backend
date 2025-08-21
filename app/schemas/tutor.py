from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class TutorListResponse(BaseModel):
    id: str = Field(..., description="Tutor ID")
    name: str = Field(..., description="Tutor name")
    subjects: List[str] = Field(..., description="Subjects taught")
    hourly_rate_cents: int = Field(..., description="Hourly rate in cents")
    average_rating: float = Field(..., description="Average rating")
    total_sessions: int = Field(..., description="Total sessions completed")
    bio: Optional[str] = Field(None, description="Tutor bio")
    is_active: bool = Field(..., description="Whether tutor is active")
    profile_image_url: Optional[str] = Field(None, description="Profile image URL")


class TutorDetailResponse(BaseModel):
    id: str = Field(..., description="Tutor ID")
    name: str = Field(..., description="Tutor name")
    email: str = Field(..., description="Tutor email")
    subjects: List[str] = Field(..., description="Subjects taught")
    hourly_rate_cents: int = Field(..., description="Hourly rate in cents")
    average_rating: float = Field(..., description="Average rating")
    total_sessions: int = Field(..., description="Total sessions completed")
    total_students: int = Field(..., description="Total students taught")
    bio: Optional[str] = Field(None, description="Tutor bio")
    education: Optional[str] = Field(None, description="Education background")
    experience_years: int = Field(..., description="Years of experience")
    is_active: bool = Field(..., description="Whether tutor is active")
    profile_image_url: Optional[str] = Field(None, description="Profile image URL")
    availability: Dict[str, Any] = Field(..., description="Availability schedule")
    reviews: List[Dict[str, Any]] = Field(default_factory=list, description="Student reviews")
    certifications: List[str] = Field(default_factory=list, description="Certifications")


class TutorSearchParams(BaseModel):
    search: Optional[str] = Field(None, description="Search by name or subject")
    subject: Optional[str] = Field(None, description="Filter by subject")
    min_rating: Optional[float] = Field(None, description="Minimum rating")
    max_rate: Optional[int] = Field(None, description="Maximum hourly rate in cents")
    available_after: Optional[datetime] = Field(None, description="Available after this time")
    limit: int = Field(20, ge=1, le=100, description="Number of results to return")
    offset: int = Field(0, ge=0, description="Number of results to skip")


class TutorAvailabilityRequest(BaseModel):
    tutor_id: str = Field(..., description="Tutor ID")
    date: Optional[str] = Field(None, description="Date in YYYY-MM-DD format")
    timezone: str = Field("UTC", description="User's timezone")


class TutorAvailabilityResponse(BaseModel):
    tutor_id: str = Field(..., description="Tutor ID")
    date: Optional[str] = Field(None, description="Date in YYYY-MM-DD format")
    timezone: str = Field(..., description="Timezone used")
    available_slots: List[Dict[str, Any]] = Field(..., description="Available time slots")
    slot_duration_minutes: int = Field(60, description="Slot duration in minutes")
