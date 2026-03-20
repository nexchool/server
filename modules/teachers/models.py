from backend.core.database import db
from backend.core.models import TenantBaseModel
from datetime import datetime
import uuid


LEAVE_TYPES = ["casual", "sick", "emergency", "unpaid", "other"]

# Default policy settings applied when a tenant has no explicit policy yet
DEFAULT_POLICY_SETTINGS = {
    "casual": {
        "total_days": 12,
        "is_unlimited": False,
        "is_carry_forward_allowed": True,
        "max_carry_forward_days": 3,
        "allow_negative": False,
        "requires_reason": False,
    },
    "sick": {
        "total_days": 10,
        "is_unlimited": False,
        "is_carry_forward_allowed": False,
        "max_carry_forward_days": 0,
        "allow_negative": False,
        "requires_reason": False,
    },
    "emergency": {
        "total_days": 3,
        "is_unlimited": False,
        "is_carry_forward_allowed": False,
        "max_carry_forward_days": 0,
        "allow_negative": True,
        "requires_reason": True,
    },
    "unpaid": {
        "total_days": 0,
        "is_unlimited": True,
        "is_carry_forward_allowed": False,
        "max_carry_forward_days": 0,
        "allow_negative": False,
        "requires_reason": False,
    },
    "other": {
        "total_days": 5,
        "is_unlimited": False,
        "is_carry_forward_allowed": False,
        "max_carry_forward_days": 0,
        "allow_negative": False,
        "requires_reason": False,
    },
}


class Teacher(TenantBaseModel):
    """
    Teacher Model

    Extends the User model with teacher-specific professional data.
    Linked to a User account for authentication. Scoped by tenant.
    """
    __tablename__ = "teachers"
    __table_args__ = (
        db.UniqueConstraint("employee_id", "tenant_id", name="uq_teachers_employee_id_tenant"),
        db.UniqueConstraint("user_id", "tenant_id", name="uq_teachers_user_id_tenant"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Link to Auth User (One-to-One)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)

    # Professional Info
    employee_id = db.Column(db.String(20), nullable=False, index=True)
    designation = db.Column(db.String(100), nullable=True)        # e.g. "Senior Teacher", "HOD"
    department = db.Column(db.String(100), nullable=True)         # e.g. "Mathematics", "Science"
    qualification = db.Column(db.String(200), nullable=True)      # e.g. "M.Ed", "Ph.D"
    specialization = db.Column(db.String(200), nullable=True)     # e.g. "Algebra", "Organic Chemistry"
    experience_years = db.Column(db.Integer, nullable=True)

    # Personal Info
    phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.Text, nullable=True)
    date_of_joining = db.Column(db.Date, nullable=True)

    # Status
    status = db.Column(db.String(20), nullable=False, default='active')  # active / inactive

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('teacher_profile', uselist=False))

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def to_dict(self, include_subjects: bool = False):
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.user.name if self.user else None,
            "email": self.user.email if self.user else None,
            "profile_picture": self.user.profile_picture_url if self.user else None,
            "employee_id": self.employee_id,
            "designation": self.designation,
            "department": self.department,
            "qualification": self.qualification,
            "specialization": self.specialization,
            "experience_years": self.experience_years,
            "phone": self.phone,
            "address": self.address,
            "date_of_joining": self.date_of_joining.isoformat() if self.date_of_joining else None,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }
        if include_subjects:
            data["subjects"] = [
                {"id": ts.subject_id, "name": ts.subject.name, "code": ts.subject.code}
                for ts in self.subject_expertise
                if ts.subject
            ]
        return data

    def __repr__(self):
        return f"<Teacher {self.employee_id}>"


class TeacherSubject(TenantBaseModel):
    """
    Teacher Subject Expertise.

    Tracks which subjects a teacher is qualified/expert to teach.
    Used by the timetable generator as a constraint.
    """
    __tablename__ = "teacher_subjects"
    __table_args__ = (
        db.UniqueConstraint("teacher_id", "subject_id", "tenant_id", name="uq_teacher_subject_tenant"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id = db.Column(db.String(36), db.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = db.Column(db.String(36), db.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    teacher = db.relationship("Teacher", backref=db.backref("subject_expertise", lazy=True, passive_deletes=True))
    subject = db.relationship("Subject", backref=db.backref("assigned_teachers", lazy=True))

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "teacher_id": self.teacher_id,
            "subject_id": self.subject_id,
            "subject_name": self.subject.name if self.subject else None,
            "subject_code": self.subject.code if self.subject else None,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self):
        return f"<TeacherSubject teacher={self.teacher_id} subject={self.subject_id}>"


class TeacherAvailability(TenantBaseModel):
    """
    Teacher Availability / Unavailability Slots.

    Records periods when a teacher is NOT available (or explicitly available).
    If no record exists for a (teacher, day, period) → teacher is available.
    day_of_week: 1=Monday … 7=Sunday.
    """
    __tablename__ = "teacher_availability"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id = db.Column(db.String(36), db.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True)
    day_of_week = db.Column(db.Integer, nullable=False)
    period_number = db.Column(db.Integer, nullable=False)
    available = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    teacher = db.relationship("Teacher", backref=db.backref("availability_slots", lazy=True, passive_deletes=True))

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "teacher_id": self.teacher_id,
            "day_of_week": self.day_of_week,
            "period_number": self.period_number,
            "available": self.available,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self):
        return f"<TeacherAvailability teacher={self.teacher_id} day={self.day_of_week} period={self.period_number}>"


class TeacherLeave(TenantBaseModel):
    """
    Teacher Leave Requests.

    Teachers submit leave requests; admins approve or reject.
    Used by the timetable generator to mark teacher as unavailable on leave dates.
    """
    __tablename__ = "teacher_leaves"

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id = db.Column(db.String(36), db.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    leave_type = db.Column(db.String(50), nullable=False, default="casual")
    reason = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    working_days = db.Column(db.Float, nullable=True)       # working (non-holiday) days in the leave period
    academic_year = db.Column(db.String(10), nullable=True)  # e.g. "2025-26", for balance tracking

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    teacher = db.relationship("Teacher", backref=db.backref("leaves", lazy=True, passive_deletes=True))

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "teacher_id": self.teacher_id,
            "teacher_name": self.teacher.user.name if self.teacher and self.teacher.user else None,
            "teacher_employee_id": self.teacher.employee_id if self.teacher else None,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "leave_type": self.leave_type,
            "reason": self.reason,
            "status": self.status,
            "working_days": self.working_days,
            "academic_year": self.academic_year,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def __repr__(self):
        return f"<TeacherLeave teacher={self.teacher_id} {self.start_date}→{self.end_date} {self.status}>"


class TeacherWorkloadRule(TenantBaseModel):
    """
    Teacher Workload Rules.

    Defines max periods per day and per week for a specific teacher.
    Used by the timetable generator to avoid over-scheduling.
    """
    __tablename__ = "teacher_workload_rules"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id = db.Column(db.String(36), db.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    max_periods_per_day = db.Column(db.Integer, nullable=False, default=6)
    max_periods_per_week = db.Column(db.Integer, nullable=False, default=30)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    teacher = db.relationship("Teacher", backref=db.backref("workload_rule", uselist=False, lazy=True, passive_deletes=True))

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "teacher_id": self.teacher_id,
            "max_periods_per_day": self.max_periods_per_day,
            "max_periods_per_week": self.max_periods_per_week,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def __repr__(self):
        return f"<TeacherWorkloadRule teacher={self.teacher_id}>"


class LeavePolicy(TenantBaseModel):
    """
    Leave Policy (per-tenant, per-leave-type).

    Defines annual allocation, carry-forward rules, and behaviour flags for
    each leave type.  Admin can customise; defaults from DEFAULT_POLICY_SETTINGS
    are auto-created on first access.
    """
    __tablename__ = "leave_policies"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "leave_type", name="uq_leave_policy_tenant_type"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    leave_type = db.Column(db.String(50), nullable=False)
    total_days = db.Column(db.Integer, nullable=False, default=0)
    is_unlimited = db.Column(db.Boolean, nullable=False, default=False)
    is_carry_forward_allowed = db.Column(db.Boolean, nullable=False, default=False)
    max_carry_forward_days = db.Column(db.Integer, nullable=False, default=0)  # 0 = no cap when CF is on
    allow_negative = db.Column(db.Boolean, nullable=False, default=False)
    requires_reason = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def save(self):
        db.session.add(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "leave_type": self.leave_type,
            "total_days": self.total_days,
            "is_unlimited": self.is_unlimited,
            "is_carry_forward_allowed": self.is_carry_forward_allowed,
            "max_carry_forward_days": self.max_carry_forward_days,
            "allow_negative": self.allow_negative,
            "requires_reason": self.requires_reason,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def __repr__(self):
        return f"<LeavePolicy tenant={self.tenant_id} type={self.leave_type} days={self.total_days}>"


class TeacherLeaveBalance(TenantBaseModel):
    """
    Teacher Leave Balance (per-teacher, per-leave-type, per-academic-year).

    Tracks how many days are allocated, used, and reserved (pending).
    Available days = allocated + carried_forward - used - pending.
    """
    __tablename__ = "teacher_leave_balances"
    __table_args__ = (
        db.UniqueConstraint(
            "teacher_id", "leave_type", "academic_year", "tenant_id",
            name="uq_leave_balance_teacher_type_year",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id = db.Column(db.String(36), db.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True)
    leave_type = db.Column(db.String(50), nullable=False)
    academic_year = db.Column(db.String(10), nullable=False)   # e.g. "2025-26"
    allocated_days = db.Column(db.Integer, nullable=False, default=0)
    used_days = db.Column(db.Float, nullable=False, default=0.0)
    pending_days = db.Column(db.Float, nullable=False, default=0.0)
    carried_forward_days = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    last_adjusted_by = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_adjusted_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    teacher = db.relationship(
        "Teacher", backref=db.backref("leave_balances", lazy=True, passive_deletes=True)
    )

    @property
    def available_days(self) -> float:
        return self.allocated_days + self.carried_forward_days - self.used_days - self.pending_days

    def save(self):
        db.session.add(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "teacher_id": self.teacher_id,
            "leave_type": self.leave_type,
            "academic_year": self.academic_year,
            "allocated_days": self.allocated_days,
            "used_days": round(self.used_days, 2),
            "pending_days": round(self.pending_days, 2),
            "carried_forward_days": self.carried_forward_days,
            "available_days": round(self.available_days, 2),
            "notes": self.notes,
            "last_adjusted_at": self.last_adjusted_at.isoformat() if self.last_adjusted_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def __repr__(self):
        return (
            f"<TeacherLeaveBalance teacher={self.teacher_id} "
            f"type={self.leave_type} year={self.academic_year} "
            f"avail={self.available_days}>"
        )
