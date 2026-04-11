"""Transport module ORM models (tenant-scoped)."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import text

from core.database import db
from core.models import TenantBaseModel


class TransportBus(TenantBaseModel):
    """School bus."""

    __tablename__ = "transport_buses"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "bus_number", name="uq_transport_buses_tenant_bus_number"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    bus_number = db.Column(db.String(50), nullable=False, index=True)
    vehicle_number = db.Column(db.String(50), nullable=True)
    capacity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active", server_default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "bus_number": self.bus_number,
            "vehicle_number": self.vehicle_number,
            "capacity": self.capacity,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TransportDriver(TenantBaseModel):
    """Bus driver (legacy dedicated table; assignments reference this)."""

    __tablename__ = "transport_drivers"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    alternate_phone = db.Column(db.String(20), nullable=True)
    license_number = db.Column(db.String(80), nullable=True)
    address = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active", server_default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "alternate_phone": self.alternate_phone,
            "license_number": self.license_number,
            "address": self.address,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TransportStaff(TenantBaseModel):
    """
    Transport staff for helpers/attendants (and optional future driver migration).
    Drivers remain on TransportDriver for backward compatibility.
    """

    __tablename__ = "transport_staff"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    alternate_phone = db.Column(db.String(20), nullable=True)
    role = db.Column(db.String(30), nullable=False, default="helper", server_default="helper")
    license_number = db.Column(db.String(80), nullable=True)
    address = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active", server_default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "alternate_phone": self.alternate_phone,
            "role": self.role,
            "license_number": self.license_number,
            "address": self.address,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TransportRoute(TenantBaseModel):
    """Pickup/drop route."""

    __tablename__ = "transport_routes"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False, index=True)
    start_point = db.Column(db.String(255), nullable=True)
    end_point = db.Column(db.String(255), nullable=True)
    approx_stops = db.Column(db.JSON, nullable=True)
    pickup_time = db.Column(db.Time, nullable=True)
    drop_time = db.Column(db.Time, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active", server_default="active")
    default_fee = db.Column(db.Numeric(12, 2), nullable=True)
    fee_cycle = db.Column(db.String(20), nullable=True, server_default="monthly")
    is_reverse_enabled = db.Column(db.Boolean, nullable=False, default=False, server_default=text("false"))
    approx_stops_needs_review = db.Column(
        db.Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    route_stop_links = db.relationship(
        "TransportRouteStop",
        back_populates="route",
        order_by="TransportRouteStop.sequence_order",
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "start_point": self.start_point,
            "end_point": self.end_point,
            "approx_stops": self.approx_stops,
            "pickup_time": self.pickup_time.isoformat() if self.pickup_time else None,
            "drop_time": self.drop_time.isoformat() if self.drop_time else None,
            "status": self.status,
            "default_fee": float(self.default_fee) if self.default_fee is not None else None,
            "fee_cycle": self.fee_cycle,
            "is_reverse_enabled": self.is_reverse_enabled,
            "approx_stops_needs_review": self.approx_stops_needs_review,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TransportRouteStop(TenantBaseModel):
    """Ordered link between a route and a global stop (junction)."""

    __tablename__ = "transport_route_stops"
    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id",
            "route_id",
            "sequence_order",
            name="uq_transport_route_stops_tenant_route_seq",
        ),
        db.UniqueConstraint(
            "tenant_id",
            "route_id",
            "stop_id",
            name="uq_transport_route_stops_tenant_route_stop",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    route_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_routes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stop_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_stops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_order = db.Column(db.Integer, nullable=False)
    pickup_time = db.Column(db.Time, nullable=True)
    drop_time = db.Column(db.Time, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    route = db.relationship("TransportRoute", back_populates="route_stop_links")
    stop = db.relationship("TransportStop", back_populates="route_links")

    def to_dict(self, include_stop: bool = True):
        d = {
            "id": self.id,
            "route_id": self.route_id,
            "stop_id": self.stop_id,
            "sequence_order": self.sequence_order,
            "pickup_time": self.pickup_time.isoformat() if self.pickup_time else None,
            "drop_time": self.drop_time.isoformat() if self.drop_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_stop and self.stop:
            d["stop"] = self.stop.to_dict()
        return d


class TransportStop(TenantBaseModel):
    """Global stop registry (reusable across routes via TransportRouteStop)."""

    __tablename__ = "transport_stops"
    __table_args__ = (
        db.Index("ix_transport_stops_route_seq", "route_id", "sequence_order"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    route_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_routes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name = db.Column(db.String(200), nullable=False)
    area = db.Column(db.String(100), nullable=True)
    landmark = db.Column(db.String(300), nullable=True)
    latitude = db.Column(db.Numeric(10, 7), nullable=True)
    longitude = db.Column(db.Numeric(10, 7), nullable=True)
    sequence_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    pickup_time = db.Column(db.Time, nullable=True)
    drop_time = db.Column(db.Time, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    route = db.relationship(
        "TransportRoute",
        foreign_keys=[route_id],
        backref=db.backref("legacy_route_stops", lazy=True),
    )
    route_links = db.relationship(
        "TransportRouteStop",
        back_populates="stop",
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "route_id": self.route_id,
            "name": self.name,
            "area": self.area,
            "landmark": self.landmark,
            "latitude": float(self.latitude) if self.latitude is not None else None,
            "longitude": float(self.longitude) if self.longitude is not None else None,
            "sequence_order": self.sequence_order,
            "pickup_time": self.pickup_time.isoformat() if self.pickup_time else None,
            "drop_time": self.drop_time.isoformat() if self.drop_time else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TransportBusAssignment(TenantBaseModel):
    """Links bus + driver + route for a date range; optional helper staff."""

    __tablename__ = "transport_bus_assignments"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    bus_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_buses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    driver_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_drivers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    route_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_routes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    helper_staff_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_staff.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active", server_default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    bus = db.relationship("TransportBus", backref=db.backref("assignments", lazy=True))
    driver = db.relationship("TransportDriver", backref=db.backref("assignments", lazy=True))
    route = db.relationship("TransportRoute", backref=db.backref("assignments", lazy=True))
    helper = db.relationship("TransportStaff", foreign_keys=[helper_staff_id])

    def to_dict(self, include_nested: bool = False):
        d = {
            "id": self.id,
            "bus_id": self.bus_id,
            "driver_id": self.driver_id,
            "route_id": self.route_id,
            "helper_staff_id": self.helper_staff_id,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_nested:
            d["bus"] = self.bus.to_dict() if self.bus else None
            d["driver"] = self.driver.to_dict() if self.driver else None
            d["route"] = self.route.to_dict() if self.route else None
            d["helper"] = self.helper.to_dict() if self.helper else None
        return d


class TransportEnrollment(TenantBaseModel):
    """Student transport enrollment (one active per student — DB partial unique)."""

    __tablename__ = "transport_enrollments"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = db.Column(
        db.String(36),
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bus_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_buses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    route_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_routes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pickup_point = db.Column(db.String(255), nullable=True)
    drop_point = db.Column(db.String(255), nullable=True)
    pickup_stop_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_stops.id", ondelete="SET NULL"),
        nullable=True,
    )
    drop_stop_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_stops.id", ondelete="SET NULL"),
        nullable=True,
    )
    monthly_fee = db.Column(db.Numeric(12, 2), nullable=False)
    fee_cycle = db.Column(db.String(20), nullable=True, server_default="monthly")
    status = db.Column(db.String(20), nullable=False, default="active", server_default="active")
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    student_fee_id = db.Column(
        db.String(36),
        db.ForeignKey("student_fees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    student = db.relationship(
        "Student",
        backref=db.backref("transport_enrollments", lazy=True),
        passive_deletes=True,
    )
    bus = db.relationship("TransportBus", backref=db.backref("enrollments", lazy=True))
    route = db.relationship("TransportRoute", backref=db.backref("enrollments", lazy=True))
    academic_year = db.relationship(
        "AcademicYear",
        foreign_keys=[academic_year_id],
        lazy=True,
    )
    pickup_stop = db.relationship(
        "TransportStop",
        foreign_keys=[pickup_stop_id],
        lazy=True,
    )
    drop_stop = db.relationship(
        "TransportStop",
        foreign_keys=[drop_stop_id],
        lazy=True,
    )

    def to_dict(self, include_nested: bool = False):
        d = {
            "id": self.id,
            "student_id": self.student_id,
            "academic_year_id": self.academic_year_id,
            "bus_id": self.bus_id,
            "route_id": self.route_id,
            "pickup_point": self.pickup_point,
            "drop_point": self.drop_point,
            "pickup_stop_id": self.pickup_stop_id,
            "drop_stop_id": self.drop_stop_id,
            "monthly_fee": float(self.monthly_fee) if self.monthly_fee is not None else None,
            "fee_cycle": self.fee_cycle,
            "status": self.status,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "student_fee_id": self.student_fee_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_nested:
            d["bus"] = self.bus.to_dict() if self.bus else None
            d["route"] = self.route.to_dict() if self.route else None
            if self.pickup_stop:
                d["pickup_stop"] = self.pickup_stop.to_dict()
            if self.drop_stop:
                d["drop_stop"] = self.drop_stop.to_dict()
        return d


class TransportFeePlan(TenantBaseModel):
    """Default monthly amount per route and academic year."""

    __tablename__ = "transport_fee_plans"
    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "route_id", "academic_year_id",
            name="uq_transport_fee_plans_tenant_route_year",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    route_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_routes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    fee_cycle = db.Column(db.String(20), nullable=True, server_default="monthly")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    route = db.relationship("TransportRoute", backref=db.backref("fee_plans", lazy=True))
    academic_year = db.relationship("AcademicYear", foreign_keys=[academic_year_id], lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "route_id": self.route_id,
            "academic_year_id": self.academic_year_id,
            "amount": float(self.amount) if self.amount is not None else None,
            "fee_cycle": self.fee_cycle,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TransportRouteSchedule(TenantBaseModel):
    """Recurring time-of-day schedule for a route (per academic year)."""

    __tablename__ = "transport_route_schedules"
    __table_args__ = (
        db.CheckConstraint("end_time > start_time", name="ck_transport_route_schedules_time_order"),
        db.CheckConstraint("shift_type IN ('pickup', 'drop')", name="ck_transport_route_schedules_shift"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    route_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_routes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bus_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_buses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    driver_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_drivers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    helper_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_staff.id", ondelete="SET NULL"),
        nullable=True,
    )
    shift_type = db.Column(db.String(10), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_reverse_enabled = db.Column(db.Boolean, nullable=False, default=False, server_default=text("false"))
    reverse_of_schedule_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_route_schedules.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    route = db.relationship("TransportRoute", backref=db.backref("schedules", lazy=True))
    bus = db.relationship("TransportBus", backref=db.backref("route_schedules", lazy=True))
    driver = db.relationship("TransportDriver", foreign_keys=[driver_id])
    helper = db.relationship(
        "TransportStaff",
        foreign_keys=[helper_id],
        backref=db.backref("schedules_as_helper", lazy=True),
    )
    reverse_of = db.relationship(
        "TransportRouteSchedule",
        remote_side=[id],
        foreign_keys=[reverse_of_schedule_id],
    )


class TransportScheduleException(TenantBaseModel):
    """One-off override or cancellation for a calendar date."""

    __tablename__ = "transport_schedule_exceptions"
    __table_args__ = (
        db.CheckConstraint(
            "exception_type IN ('override', 'cancellation')",
            name="ck_transport_schedule_exceptions_type",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exception_date = db.Column(db.Date, nullable=False)
    exception_type = db.Column(db.String(20), nullable=False)
    route_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_routes.id", ondelete="CASCADE"),
        nullable=True,
    )
    bus_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_buses.id", ondelete="SET NULL"),
        nullable=True,
    )
    driver_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_drivers.id", ondelete="SET NULL"),
        nullable=True,
    )
    helper_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_staff.id", ondelete="SET NULL"),
        nullable=True,
    )
    shift_type = db.Column(db.String(10), nullable=True)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    schedule_id = db.Column(
        db.String(36),
        db.ForeignKey("transport_route_schedules.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    route = db.relationship("TransportRoute", foreign_keys=[route_id])
    bus = db.relationship("TransportBus", foreign_keys=[bus_id])
    driver = db.relationship("TransportDriver", foreign_keys=[driver_id])
    helper = db.relationship("TransportStaff", foreign_keys=[helper_id])
    target_schedule = db.relationship(
        "TransportRouteSchedule",
        foreign_keys=[schedule_id],
    )
