"""Hostel module ORM models (tenant-scoped)."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import ColumnDefault
from core.database import db
from core.models import TenantBaseModel


class Hostel(TenantBaseModel):
    """Hostel entity with rooms and beds."""

    __tablename__ = "hostels"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "name", name="uq_hostels_tenant_name"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False, index=True)
    warden_name = db.Column(db.String(200), nullable=True)
    warden_phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.Text, nullable=True)
    capacity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active", server_default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    deleted_at = db.Column(db.DateTime, nullable=True)

    rooms = db.relationship(
        "HostelRoom",
        back_populates="hostel",
        cascade="all, delete-orphan",
        lazy=True,
    )

    def __init__(self, **kwargs):
        """Initialize with defaults for status."""
        if 'status' not in kwargs:
            kwargs['status'] = 'active'
        super().__init__(**kwargs)

    def to_dict(self):
        """Serialize hostel for API response."""
        return {
            "id": self.id,
            "name": self.name,
            "warden_name": self.warden_name,
            "warden_phone": self.warden_phone,
            "address": self.address,
            "capacity": self.capacity,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class HostelRoom(TenantBaseModel):
    """Room within a hostel."""

    __tablename__ = "hostel_rooms"
    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "hostel_id", "room_number",
            name="uq_hostel_rooms_tenant_hostel_room_number"
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    hostel_id = db.Column(
        db.String(36),
        db.ForeignKey("hostels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_number = db.Column(db.String(50), nullable=False, index=True)
    capacity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active", server_default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    deleted_at = db.Column(db.DateTime, nullable=True)

    hostel = db.relationship(
        "Hostel",
        back_populates="rooms",
        foreign_keys=[hostel_id],
    )
    beds = db.relationship(
        "HostelBed",
        back_populates="room",
        cascade="all, delete-orphan",
        lazy=True,
    )

    def __init__(self, **kwargs):
        """Initialize with Python-level defaults so transient objects expose them."""
        if 'status' not in kwargs:
            kwargs['status'] = 'active'
        super().__init__(**kwargs)

    def to_dict(self):
        """Serialize room for API response."""
        return {
            "id": self.id,
            "hostel_id": self.hostel_id,
            "room_number": self.room_number,
            "capacity": self.capacity,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class HostelBed(TenantBaseModel):
    """Individual bed within a hostel room."""

    __tablename__ = "hostel_beds"
    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "room_id", "bed_number",
            name="uq_hostel_beds_tenant_room_bed_number"
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id = db.Column(
        db.String(36),
        db.ForeignKey("hostel_rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bed_number = db.Column(db.String(50), nullable=False, index=True)
    is_allocated = db.Column(db.Boolean, nullable=False, default=False, server_default="false")
    allocated_to_student_id = db.Column(
        db.String(36),
        db.ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = db.Column(db.String(20), nullable=False, default="active", server_default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    deleted_at = db.Column(db.DateTime, nullable=True)

    room = db.relationship(
        "HostelRoom",
        back_populates="beds",
        foreign_keys=[room_id],
    )
    allocated_to_student = db.relationship(
        "Student",
        foreign_keys=[allocated_to_student_id],
        backref=db.backref("hostel_bed", uselist=False),
    )

    def __init__(self, **kwargs):
        """Initialize with Python-level defaults so transient objects expose them."""
        if 'status' not in kwargs:
            kwargs['status'] = 'active'
        if 'is_allocated' not in kwargs:
            kwargs['is_allocated'] = False
        super().__init__(**kwargs)

    def to_dict(self):
        """Serialize bed for API response."""
        return {
            "id": self.id,
            "room_id": self.room_id,
            "bed_number": self.bed_number,
            "is_allocated": self.is_allocated,
            "allocated_to_student_id": self.allocated_to_student_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }
