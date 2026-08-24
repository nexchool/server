"""Academic Cycle — the dated period an academic year is actually operated in.

`AcademicYear` is what the organization reports under: "2026-27". It is one
label for the whole tenant, and that is correct — a trust running GSEB and CBSE
has one 2026-27, not two.

What it cannot say is *when*. GSEB runs June to April and CBSE runs April to
March; a Grade 11 vacation batch runs for forty days in May. Those are three
operating periods inside one reporting year, and before this model existed the
year's own `start_date`/`end_date` had to stand for all of them.

**A cycle names no applicability.** There is deliberately no `programme_id`,
`grade_id`, `stream_id` or `school_unit_id` here. Which classes run in a cycle
is answered by the classes that point at it — a query, not a claim. Declaring
it here would let a cycle say "CBSE, grades 9-12" while a class in it says
"GSEB, grade 8", and then two sources disagree about the same fact with nothing
to arbitrate.

**There is no globally current cycle**, and none should be added. Several are
legitimately live at once. Context answers the question instead: a class knows
its cycle, an enrollment knows its class, a calendar knows its cycle.
"""

import uuid

from sqlalchemy import CheckConstraint, Index, text

from core.database import db
from core.models import TenantBaseModel
from core.school_time import utc_now


# The school's ordinary year. Every existing academic year became one of these.
CYCLE_KIND_MAIN = "main"
# A vacation batch, a coaching programme, a remedial or weekend course — a
# period that runs alongside the main one rather than instead of it.
CYCLE_KIND_SHORT_COURSE = "short_course"

CYCLE_KINDS = (CYCLE_KIND_MAIN, CYCLE_KIND_SHORT_COURSE)


class AcademicCycle(TenantBaseModel):
    """A dated operating period within an academic year."""

    __tablename__ = "academic_cycles"
    __table_args__ = (
        # A cycle is chosen by name in a picker, so two called "GSEB Main" in
        # one year would be indistinguishable. Same rule academic_years and
        # academic_terms already carry.
        Index(
            "uq_academic_cycles_year_name",
            "tenant_id",
            "academic_year_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_academic_cycles_year", "tenant_id", "academic_year_id"),
        Index("idx_academic_cycles_dates", "tenant_id", "start_date", "end_date"),
        CheckConstraint(
            "cycle_kind IN ('main', 'short_course')",
            name="ck_academic_cycles_kind",
        ),
        CheckConstraint(
            "start_date <= end_date", name="ck_academic_cycles_dates_ordered"
        ),
        # Composite-FK targets. `(academic_year_id, id)` is what lets a class,
        # a term and a calendar declare that the cycle they name belongs to the
        # year they name — so the two can never drift apart.
        db.UniqueConstraint("tenant_id", "id", name="uq_academic_cycles_tenant_id_id"),
        db.UniqueConstraint(
            "academic_year_id", "id", name="uq_academic_cycles_year_id_id"
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    cycle_kind = db.Column(
        db.String(20),
        nullable=False,
        default=CYCLE_KIND_MAIN,
        server_default=text("'main'"),
    )

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    academic_year = db.relationship("AcademicYear", foreign_keys=[academic_year_id])

    @property
    def is_main(self) -> bool:
        return self.cycle_kind == CYCLE_KIND_MAIN

    def covers(self, on) -> bool:
        """Whether this cycle is running on the given date."""
        return self.start_date <= on <= self.end_date

    def to_dict(self):
        return {
            "id": self.id,
            "academic_year_id": self.academic_year_id,
            "name": self.name,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "cycle_kind": self.cycle_kind,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<AcademicCycle {self.name} {self.start_date}–{self.end_date}>"
