"""Employment — the Staff relationship between a Person and the organization.

Employment is what the school and the person agreed; it says nothing about
teaching. A receptionist and a principal are Staff on the same terms as a
teacher, and teaching is an academic participation layered on top (ADR-005).

Where someone stands and how they are engaged are separate dimensions. Merging
them would make a permanent teacher on maternity leave, or a contract teacher
serving notice, impossible to record.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from core.database import db
from core.models import TenantBaseModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# Where the person stands right now. Every value is a real business event, so
# the record explains what happened rather than only that someone is inactive.
EMPLOYMENT_STATUS_WORKING = "working"
EMPLOYMENT_STATUS_PROBATION = "probation"
EMPLOYMENT_STATUS_ON_LEAVE = "on_leave"
EMPLOYMENT_STATUS_NOTICE_PERIOD = "notice_period"
EMPLOYMENT_STATUS_SUSPENDED = "suspended"
EMPLOYMENT_STATUS_RESIGNED = "resigned"
EMPLOYMENT_STATUS_RETIRED = "retired"
EMPLOYMENT_STATUS_TERMINATED = "terminated"
# Carried over from records that stored only that someone had gone. Never chosen
# for a departure the platform witnesses — those say why.
EMPLOYMENT_STATUS_LEFT = "left"

EMPLOYMENT_STATUSES = (
    EMPLOYMENT_STATUS_WORKING,
    EMPLOYMENT_STATUS_PROBATION,
    EMPLOYMENT_STATUS_ON_LEAVE,
    EMPLOYMENT_STATUS_NOTICE_PERIOD,
    EMPLOYMENT_STATUS_SUSPENDED,
    EMPLOYMENT_STATUS_RESIGNED,
    EMPLOYMENT_STATUS_RETIRED,
    EMPLOYMENT_STATUS_TERMINATED,
    EMPLOYMENT_STATUS_LEFT,
)

# Statuses in which the person is still employed, whatever they are doing today.
EMPLOYED_STATUSES = frozenset(
    {
        EMPLOYMENT_STATUS_WORKING,
        EMPLOYMENT_STATUS_PROBATION,
        EMPLOYMENT_STATUS_ON_LEAVE,
        EMPLOYMENT_STATUS_NOTICE_PERIOD,
        EMPLOYMENT_STATUS_SUSPENDED,
    }
)

# Being employed and being able to act are different questions. Suspension is a
# disciplinary measure whose whole purpose is to stop someone acting, so it
# withholds authority without ending their employment. Leave does not: someone
# on maternity leave is simply absent, not distrusted.
AUTHORITY_BEARING_STATUSES = frozenset(EMPLOYED_STATUSES - {EMPLOYMENT_STATUS_SUSPENDED})

# The basis on which the person is engaged.
EMPLOYMENT_TYPE_PERMANENT = "permanent"
EMPLOYMENT_TYPE_CONTRACT = "contract"
EMPLOYMENT_TYPE_VISITING = "visiting"
EMPLOYMENT_TYPE_PART_TIME = "part_time"
EMPLOYMENT_TYPE_TEMPORARY = "temporary"

EMPLOYMENT_TYPES = (
    EMPLOYMENT_TYPE_PERMANENT,
    EMPLOYMENT_TYPE_CONTRACT,
    EMPLOYMENT_TYPE_VISITING,
    EMPLOYMENT_TYPE_PART_TIME,
    EMPLOYMENT_TYPE_TEMPORARY,
)


class Staff(TenantBaseModel):
    """A Person employed by the organization.

    Created once, when the person joins. Leaving and returning does not create a
    second Staff relationship — it opens a new employment period.
    """

    __tablename__ = "staff"

    id = db.Column(db.String(36), primary_key=True, default=_new_id)

    person_id = db.Column(
        db.String(36),
        db.ForeignKey("persons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # A relationship, not merely a column: it is what orders the person's insert
    # ahead of the employment that references them, and it is how People answers
    # "does this person work here?" without going looking (see relationships.py).
    person = db.relationship(
        "Person",
        foreign_keys=[person_id],
        backref=db.backref("employments", lazy=True),
    )

    # The school's own identifier. Nullable because organizations migrating from
    # records that never captured one should not be given an invented number.
    employee_number = db.Column(db.String(50), nullable=True)

    # Free text until the designations catalogue exists; it becomes a reference
    # then, so that a job title is defined in one place.
    designation = db.Column(db.Text, nullable=True)
    department_id = db.Column(
        db.String(36),
        db.ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    department = db.relationship("Department", foreign_keys=[department_id])

    employment_status = db.Column(
        db.String(30), nullable=False, default=EMPLOYMENT_STATUS_WORKING
    )
    employment_type = db.Column(db.String(30), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "person_id", name="uq_staff_tenant_person"),
        db.CheckConstraint(
            "employment_status IN ("
            "'working','probation','on_leave','notice_period','suspended',"
            "'resigned','retired','terminated','left')",
            name="ck_staff_employment_status",
        ),
    )

    @property
    def is_employed(self) -> bool:
        return self.employment_status in EMPLOYED_STATUSES

    @property
    def may_act(self) -> bool:
        """Whether this person may act on the organization's behalf.

        Narrower than employment: a suspended employee remains employed and
        keeps their record, but holds no authority while suspended.
        """
        return self.employment_status in AUTHORITY_BEARING_STATUSES

    @property
    def joined_on(self):
        """When this person first came to work here.

        Employment covers periods, and someone who resigned and was later
        re-appointed has more than one. "Date of joining" means the first of
        them — the day the school first took them on.
        """
        started = [period.joined_on for period in self.periods if period.joined_on]
        return min(started) if started else None

    @classmethod
    def joined_on_column(cls):
        """``joined_on`` as something a query can filter and sort by.

        The same fact as the property above, expressed in SQL so that reading a
        joining date and searching by one can never disagree.
        """
        from sqlalchemy import func, select

        return (
            select(func.min(StaffEmploymentPeriod.joined_on))
            .where(StaffEmploymentPeriod.staff_id == cls.id)
            .correlate(cls)
            .scalar_subquery()
        )

    def __repr__(self) -> str:
        return f"<Staff {self.id} person={self.person_id} {self.employment_status}>"


class StaffEmploymentPeriod(TenantBaseModel):
    """One continuous stretch of employment.

    A person who resigns and is later re-appointed has two periods against the
    same Staff relationship, so their history reads as it happened.
    """

    __tablename__ = "staff_employment_periods"

    id = db.Column(db.String(36), primary_key=True, default=_new_id)

    staff_id = db.Column(
        db.String(36),
        db.ForeignKey("staff.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    staff = db.relationship(
        "Staff",
        foreign_keys=[staff_id],
        backref=db.backref("periods", lazy=True),
    )

    joined_on = db.Column(db.Date, nullable=True)
    left_on = db.Column(db.Date, nullable=True)
    # Why this period ended, using the same vocabulary as employment status.
    end_reason = db.Column(db.String(30), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    @property
    def is_open(self) -> bool:
        """True while this is the period the person is currently serving.

        A period that ended on a date nobody recorded still carries an end
        reason, so absence of a leaving date alone does not mean ongoing.
        """
        return self.left_on is None and self.end_reason is None

    def __repr__(self) -> str:
        return f"<StaffEmploymentPeriod {self.id} staff={self.staff_id}>"
