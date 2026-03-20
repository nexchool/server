"""
Timetable Schemas

Validation and serialization schemas for TimetableSlot API.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TimetableSlotCreate:
    """Schema for creating a timetable slot."""

    class_id: str
    subject_id: str
    teacher_id: str
    day_of_week: int
    period_number: int
    start_time: str  # "HH:MM" or "HH:MM:SS"
    end_time: str
    room: Optional[str] = None


@dataclass
class TimetableSlotUpdate:
    """Schema for updating a timetable slot. All fields optional."""

    class_id: Optional[str] = None
    subject_id: Optional[str] = None
    teacher_id: Optional[str] = None
    day_of_week: Optional[int] = None
    period_number: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    room: Optional[str] = None


@dataclass
class TimetableSlotResponse:
    """Schema for timetable slot API response."""

    id: str
    class_id: str
    subject_id: str
    subject_name: Optional[str]
    teacher_id: str
    teacher_name: Optional[str]
    day_of_week: int
    period_number: int
    start_time: str
    end_time: str
    room: Optional[str]
    tenant_id: str
    created_at: str
    updated_at: str
