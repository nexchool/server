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


class HostelAllocation(TenantBaseModel):
    """Student → Bed allocation record (current + historical)."""

    __tablename__ = "hostel_allocations"

    # Status values
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_MOVED = "moved"
    STATUS_VALUES = (STATUS_ACTIVE, STATUS_COMPLETED, STATUS_MOVED)

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = db.Column(
        db.String(36),
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hostel_id = db.Column(
        db.String(36),
        db.ForeignKey("hostels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_id = db.Column(
        db.String(36),
        db.ForeignKey("hostel_rooms.id", ondelete="CASCADE"),
        nullable=False,
    )
    bed_id = db.Column(
        db.String(36),
        db.ForeignKey("hostel_beds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="SET NULL"),
        nullable=True,
    )
    check_in_at = db.Column(db.DateTime, nullable=False)
    check_out_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    deleted_at = db.Column(db.DateTime, nullable=True)

    student = db.relationship(
        "Student",
        foreign_keys=[student_id],
        backref=db.backref("hostel_allocations", lazy=True),
    )
    hostel = db.relationship("Hostel", foreign_keys=[hostel_id])
    room = db.relationship("HostelRoom", foreign_keys=[room_id])
    bed = db.relationship("HostelBed", foreign_keys=[bed_id])

    def __init__(self, **kwargs):
        """Initialize with Python-level defaults so transient objects expose them."""
        if "status" not in kwargs:
            kwargs["status"] = "active"
        super().__init__(**kwargs)

    @property
    def is_active(self) -> bool:
        """True if allocation is currently active (not checked out)."""
        return self.status == "active" and self.check_out_at is None and self.deleted_at is None

    def to_dict(self) -> dict:
        """Serialize allocation for API response."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "student_id": self.student_id,
            "hostel_id": self.hostel_id,
            "room_id": self.room_id,
            "bed_id": self.bed_id,
            "academic_year_id": self.academic_year_id,
            "check_in_at": self.check_in_at.isoformat() if self.check_in_at else None,
            "check_out_at": self.check_out_at.isoformat() if self.check_out_at else None,
            "status": self.status,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class HostelVisitor(TenantBaseModel):
    """Repeat-visitor profile keyed by phone within a tenant."""

    __tablename__ = "hostel_visitors"
    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "phone", name="uq_hostel_visitors_tenant_phone"
        ),
    )

    # Relation types
    RELATION_FATHER = "father"
    RELATION_MOTHER = "mother"
    RELATION_SIBLING = "sibling"
    RELATION_GUARDIAN = "guardian"
    RELATION_OTHER = "other"
    RELATION_VALUES = (
        RELATION_FATHER,
        RELATION_MOTHER,
        RELATION_SIBLING,
        RELATION_GUARDIAN,
        RELATION_OTHER,
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    phone = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    relation_type = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    visitor_logs = db.relationship(
        "HostelVisitorLog",
        back_populates="visitor",
        cascade="all, delete-orphan",
        lazy=True,
    )

    def to_dict(self) -> dict:
        """Serialize visitor for API response."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "phone": self.phone,
            "name": self.name,
            "relation_type": self.relation_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class HostelVisitorLog(TenantBaseModel):
    """Each visitor check-in/check-out event (audit trail)."""

    __tablename__ = "hostel_visitor_logs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    visitor_id = db.Column(
        db.String(36),
        db.ForeignKey("hostel_visitors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id = db.Column(
        db.String(36),
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hostel_id = db.Column(
        db.String(36),
        db.ForeignKey("hostels.id", ondelete="CASCADE"),
        nullable=False,
    )
    room_id = db.Column(
        db.String(36),
        db.ForeignKey("hostel_rooms.id", ondelete="SET NULL"),
        nullable=True,
    )
    check_in_at = db.Column(db.DateTime, nullable=False)
    check_out_at = db.Column(db.DateTime, nullable=True)
    purpose = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    visitor = db.relationship(
        "HostelVisitor",
        back_populates="visitor_logs",
        foreign_keys=[visitor_id],
    )
    student = db.relationship("Student", foreign_keys=[student_id])
    hostel = db.relationship("Hostel", foreign_keys=[hostel_id])
    room = db.relationship("HostelRoom", foreign_keys=[room_id])

    @property
    def is_currently_inside(self) -> bool:
        """True if visitor hasn't checked out yet (and not soft-deleted)."""
        return self.check_out_at is None and self.deleted_at is None

    def to_dict(self) -> dict:
        """Serialize visitor log for API response."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "visitor_id": self.visitor_id,
            "student_id": self.student_id,
            "hostel_id": self.hostel_id,
            "room_id": self.room_id,
            "check_in_at": self.check_in_at.isoformat() if self.check_in_at else None,
            "check_out_at": self.check_out_at.isoformat() if self.check_out_at else None,
            "purpose": self.purpose,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }
