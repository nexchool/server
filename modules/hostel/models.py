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
    # Used to group rooms on the rooms grid (e.g. "Ground Floor", "1st Floor").
    floor = db.Column(
        db.String(50), nullable=False, default="Ground Floor",
        server_default="Ground Floor",
    )
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
            "floor": self.floor,
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


class HostelGatepass(TenantBaseModel):
    """Student night/day-out gatepass with state machine."""

    __tablename__ = "hostel_gatepasses"

    # Gatepass types
    TYPE_DAY_OUT = "day_out"
    TYPE_NIGHT_OUT = "night_out"
    TYPE_VALUES = (TYPE_DAY_OUT, TYPE_NIGHT_OUT)

    # Status state machine
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_ACTIVE = "active"
    STATUS_CLOSED = "closed"
    STATUS_REJECTED = "rejected"
    STATUS_OVERDUE = "overdue"
    STATUS_VALUES = (
        STATUS_PENDING,
        STATUS_APPROVED,
        STATUS_ACTIVE,
        STATUS_CLOSED,
        STATUS_REJECTED,
        STATUS_OVERDUE,
    )

    # Parent consent status (informational only in v1; security guard calls directly)
    CONSENT_NOT_REQUIRED = "not_required"
    CONSENT_PENDING = "pending"
    CONSENT_GIVEN = "given"
    CONSENT_REJECTED = "rejected"
    CONSENT_VALUES = (
        CONSENT_NOT_REQUIRED,
        CONSENT_PENDING,
        CONSENT_GIVEN,
        CONSENT_REJECTED,
    )

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
    type = db.Column(db.String(20), nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    requested_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    actual_out_at = db.Column(db.DateTime, nullable=True)
    actual_in_at = db.Column(db.DateTime, nullable=True)
    departure_datetime = db.Column(db.DateTime, nullable=False)
    expected_return_datetime = db.Column(db.DateTime, nullable=False)
    reason = db.Column(db.String(500), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    parent_phone = db.Column(db.String(20), nullable=False)
    parent_consent_status = db.Column(
        db.String(20),
        nullable=False,
        default="not_required",
        server_default="not_required",
    )
    parent_consent_notified_at = db.Column(db.DateTime, nullable=True)
    parent_notification_type = db.Column(db.String(50), nullable=True)
    approved_by_user_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    deleted_at = db.Column(db.DateTime, nullable=True)

    student = db.relationship("Student", foreign_keys=[student_id])
    hostel = db.relationship("Hostel", foreign_keys=[hostel_id])
    audit_logs = db.relationship(
        "HostelGatepassAudit",
        back_populates="gatepass",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="HostelGatepassAudit.created_at",
    )

    def __init__(self, **kwargs):
        """Initialize with Python-level defaults so transient objects expose them."""
        if "status" not in kwargs:
            kwargs["status"] = "pending"
        if "parent_consent_status" not in kwargs:
            kwargs["parent_consent_status"] = "not_required"
        super().__init__(**kwargs)

    @property
    def is_overdue(self) -> bool:
        """True if active gatepass has passed its expected return time.

        Note: This is a Python-side check used at read time. The
        background job is responsible for transitioning status to 'overdue'.
        Grace period is applied by the job, not here.
        """
        if self.status != self.STATUS_ACTIVE:
            return False
        if self.expected_return_datetime is None:
            return False
        return datetime.utcnow() > self.expected_return_datetime

    def can_transition_to(self, new_status: str) -> bool:
        """Check whether a state transition is legal.

        Allowed transitions:
          pending  -> approved | rejected
          approved -> active   (gatekeeper checkout)
          active   -> closed   (gatekeeper checkin)
          active   -> overdue  (system job)
        """
        allowed = {
            self.STATUS_PENDING: {self.STATUS_APPROVED, self.STATUS_REJECTED},
            self.STATUS_APPROVED: {self.STATUS_ACTIVE},
            self.STATUS_ACTIVE: {self.STATUS_CLOSED, self.STATUS_OVERDUE},
            self.STATUS_CLOSED: set(),
            self.STATUS_REJECTED: set(),
            self.STATUS_OVERDUE: {self.STATUS_CLOSED},  # late return still allowed
        }
        return new_status in allowed.get(self.status, set())

    def to_dict(self) -> dict:
        """Serialize gatepass for API response."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "student_id": self.student_id,
            "hostel_id": self.hostel_id,
            "type": self.type,
            "status": self.status,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "actual_out_at": self.actual_out_at.isoformat() if self.actual_out_at else None,
            "actual_in_at": self.actual_in_at.isoformat() if self.actual_in_at else None,
            "departure_datetime": (
                self.departure_datetime.isoformat() if self.departure_datetime else None
            ),
            "expected_return_datetime": (
                self.expected_return_datetime.isoformat()
                if self.expected_return_datetime
                else None
            ),
            "reason": self.reason,
            "notes": self.notes,
            "parent_phone": self.parent_phone,
            "parent_consent_status": self.parent_consent_status,
            "parent_consent_notified_at": (
                self.parent_consent_notified_at.isoformat()
                if self.parent_consent_notified_at
                else None
            ),
            "parent_notification_type": self.parent_notification_type,
            "approved_by_user_id": self.approved_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class HostelGatepassAudit(db.Model):
    """Append-only audit log for every gatepass state change.

    Not tenant-scoped directly; tenant is inferred via gatepass_id.
    Never deleted; preserved for compliance.
    """

    __tablename__ = "hostel_gatepass_audit"

    # Action types
    ACTION_CREATED = "created"
    ACTION_APPROVED = "approved"
    ACTION_REJECTED = "rejected"
    ACTION_CHECKOUT = "checkout"
    ACTION_CHECKIN = "checkin"
    ACTION_MARKED_OVERDUE = "marked_overdue"
    ACTION_VALUES = (
        ACTION_CREATED,
        ACTION_APPROVED,
        ACTION_REJECTED,
        ACTION_CHECKOUT,
        ACTION_CHECKIN,
        ACTION_MARKED_OVERDUE,
    )

    # Actor types
    ACTOR_STUDENT = "student"
    ACTOR_WARDEN = "warden"
    ACTOR_GATEKEEPER = "gatekeeper"
    ACTOR_SYSTEM = "system"
    ACTOR_VALUES = (
        ACTOR_STUDENT,
        ACTOR_WARDEN,
        ACTOR_GATEKEEPER,
        ACTOR_SYSTEM,
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    gatepass_id = db.Column(
        db.String(36),
        db.ForeignKey("hostel_gatepasses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action = db.Column(db.String(50), nullable=False)
    actor_type = db.Column(db.String(20), nullable=False)
    actor_id = db.Column(db.String(36), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    gatepass = db.relationship(
        "HostelGatepass",
        back_populates="audit_logs",
        foreign_keys=[gatepass_id],
    )

    def to_dict(self) -> dict:
        """Serialize audit entry for API response."""
        return {
            "id": self.id,
            "gatepass_id": self.gatepass_id,
            "action": self.action,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
