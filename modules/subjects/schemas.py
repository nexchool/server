"""
Subject Schemas

Validation and serialization schemas for Subject API.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SubjectCreate:
    """Schema for creating a subject."""

    name: str
    code: Optional[str] = None
    description: Optional[str] = None


@dataclass
class SubjectUpdate:
    """Schema for updating a subject. All fields optional."""

    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None


@dataclass
class SubjectResponse:
    """Schema for subject API response."""

    id: str
    name: str
    code: Optional[str]
    description: Optional[str]
    tenant_id: str
    created_at: str
    updated_at: str
