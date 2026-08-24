"""an examination is an event; a paper is what a student sits

Seven tables and one added unique constraint. Each is here because an existing
entity could not correctly own the concept:

- `exam_types` — Unit Test, Preliminary, Board. A **table** because these
  differ by school and by board, and adding one must never be a deploy. The
  same rule `streams` follows. Nothing branches on the value.
- `examinations` — the event. Belongs to an academic **cycle**, because that is
  when the school is open. It declares no programme, grade, stream or class:
  its papers do (ADR-016).
- `exam_papers` — one subject, one section, one date. Theory and practical are
  two papers, distinguished by `component_label`, because that is what a school
  actually sits.
- `exam_marks` — a student's outcome, with a CHECK making absence
  representable: `marks_obtained` is NULL unless they were present. A zero and
  an absence must never be the same row.
- `grading_schemes` / `grading_bands` — how a number becomes a grade. Kept
  outside the examination module's ownership because attendance and conduct
  grades will want the same machinery.
- `exam_results` — the published snapshot, versioned. A grading scheme edited
  in December must not change what a parent was told in August.
- `examination_lifecycle_events` — append-only, the shape student and staff
  lifecycles already use.

Deliberately NOT created: any table for exam documents. `documents` already
serves every domain through `(owner_kind, owner_id)` — its own docstring uses
`exam_paper` as the worked example — so question papers hang off the paper and
answer sheets off the mark (ADR-018).

`students` gains `UNIQUE (tenant_id, id)` so marks and results can declare
composite foreign keys against it. That is the exit the debt register names for
the FK pairs that can still legally cross tenants.

Revision ID: 114_an_examination_is_an_event_with_papers
Revises: 113_a_term_is_named_within_its_cycle
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "114_an_examination_is_an_event_with_papers"
down_revision = "113_a_term_is_named_within_its_cycle"
branch_labels = None
depends_on = None

# Common in Indian schools, and every one of them editable or removable. Seeded
# so a school opening its first examination finds something to choose rather
# than an empty list; written out here rather than imported, because a
# migration has to mean the same thing in five years.
_SEED_TYPES = [
    ("Unit Test", "UT", 10),
    ("Periodic Test", "PT", 20),
    ("Half Yearly", "HY", 30),
    ("Preliminary", "PRE", 40),
    ("Final", "FIN", 50),
    ("Practical", "PRAC", 60),
    ("Mock Test", "MOCK", 70),
]

_SEED_PER_TENANT = sa.text(
    """
    INSERT INTO exam_types (id, tenant_id, name, code, sequence, created_at, updated_at)
    SELECT md5('exam_type:' || t.id || ':' || :name)::uuid::text,
           t.id, :name, :code, :sequence, now(), now()
      FROM tenants t
    ON CONFLICT DO NOTHING
    """
)


def _timestamps():
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )


def upgrade():
    bind = op.get_bind()

    # Composite-FK target for marks and results.
    op.create_unique_constraint(
        "uq_students_tenant_id_id", "students", ["tenant_id", "id"]
    )

    # ---------------------------------------------------------------- types
    op.create_table(
        "exam_types",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("code", sa.String(32), nullable=True),
        sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_exam_types_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_exam_types_tenant_id_id"),
    )
    op.create_index("idx_exam_types_tenant", "exam_types", ["tenant_id"])
    op.create_index("idx_exam_types_sequence", "exam_types", ["sequence"])
    op.create_index("idx_exam_types_deleted_at", "exam_types", ["deleted_at"])
    op.create_index(
        "uq_exam_types_tenant_name", "exam_types", ["tenant_id", "name"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_exam_types_tenant_code", "exam_types", ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("code IS NOT NULL AND deleted_at IS NULL"),
    )
    for name, code, sequence in _SEED_TYPES:
        bind.execute(_SEED_PER_TENANT, {"name": name, "code": code, "sequence": sequence})

    # -------------------------------------------------------------- grading
    #
    # No bands are seeded. A+ at 90 is CBSE's rule, not GSEB's and not every
    # school's, and inventing one would put a school's grading policy in a
    # migration.
    op.create_table(
        "grading_schemes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "scheme_type", sa.String(20), nullable=False, server_default="percentage"
        ),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_grading_schemes_tenant",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "scheme_type IN ('percentage', 'letter', 'grade_point', 'pass_fail')",
            name="ck_grading_schemes_type",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_grading_schemes_tenant_id_id"
        ),
    )
    op.create_index("idx_grading_schemes_tenant", "grading_schemes", ["tenant_id"])
    op.create_index(
        "idx_grading_schemes_deleted_at", "grading_schemes", ["deleted_at"]
    )
    op.create_index(
        "uq_grading_schemes_tenant_name", "grading_schemes", ["tenant_id", "name"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "grading_bands",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("grading_scheme_id", sa.String(36), nullable=False),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("min_value", sa.Numeric(6, 2), nullable=False),
        sa.Column("max_value", sa.Numeric(6, 2), nullable=False),
        sa.Column("grade_point", sa.Numeric(4, 2), nullable=True),
        sa.Column("is_pass", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_grading_bands_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "grading_scheme_id"],
            ["grading_schemes.tenant_id", "grading_schemes.id"],
            name="fk_grading_bands_scheme", ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "min_value <= max_value", name="ck_grading_bands_bounds_ordered"
        ),
    )
    op.create_index(
        "idx_grading_bands_scheme", "grading_bands", ["tenant_id", "grading_scheme_id"]
    )

    # --------------------------------------------------------- examinations
    op.create_table(
        "examinations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("academic_cycle_id", sa.String(36), nullable=False),
        sa.Column("academic_term_id", sa.String(36), nullable=True),
        sa.Column("exam_type_id", sa.String(36), nullable=False),
        sa.Column("grading_scheme_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("exam_window_id", sa.String(36), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=True),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_examinations_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "academic_cycle_id"],
            ["academic_cycles.tenant_id", "academic_cycles.id"],
            name="fk_examinations_cycle", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["academic_term_id"], ["academic_terms.id"],
            name="fk_examinations_term", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exam_type_id"],
            ["exam_types.tenant_id", "exam_types.id"],
            name="fk_examinations_exam_type", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "grading_scheme_id"],
            ["grading_schemes.tenant_id", "grading_schemes.id"],
            name="fk_examinations_grading_scheme", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["exam_window_id"], ["exam_windows.id"],
            name="fk_examinations_exam_window", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            name="fk_examinations_created_by", ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'scheduled', 'marks_entry', 'published', 'cancelled')",
            name="ck_examinations_status",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_examinations_tenant_id_id"),
    )
    op.create_index("idx_examinations_tenant", "examinations", ["tenant_id"])
    op.create_index(
        "idx_examinations_cycle", "examinations", ["tenant_id", "academic_cycle_id"]
    )
    op.create_index("idx_examinations_status", "examinations", ["tenant_id", "status"])
    op.create_index("idx_examinations_term", "examinations", ["academic_term_id"])
    op.create_index("idx_examinations_window", "examinations", ["exam_window_id"])
    op.create_index("idx_examinations_deleted_at", "examinations", ["deleted_at"])
    op.create_index(
        "uq_examinations_cycle_name",
        "examinations",
        ["tenant_id", "academic_cycle_id", "name"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ---------------------------------------------------------------- papers
    op.create_table(
        "exam_papers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("examination_id", sa.String(36), nullable=False),
        sa.Column("class_subject_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(36), nullable=False),
        sa.Column(
            "component_label", sa.String(40), nullable=False, server_default=""
        ),
        sa.Column("exam_date", sa.Date, nullable=True),
        sa.Column("starts_at", sa.Time, nullable=True),
        sa.Column("ends_at", sa.Time, nullable=True),
        sa.Column("venue", sa.String(120), nullable=True),
        sa.Column("max_marks", sa.Numeric(6, 2), nullable=False),
        sa.Column("pass_marks", sa.Numeric(6, 2), nullable=True),
        sa.Column("weight", sa.Numeric(6, 2), nullable=True),
        sa.Column("instructions", sa.Text, nullable=True),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_exam_papers_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "examination_id"],
            ["examinations.tenant_id", "examinations.id"],
            name="fk_exam_papers_examination", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "class_subject_id"],
            ["class_subjects.tenant_id", "class_subjects.id"],
            name="fk_exam_papers_class_subject", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["class_id"], ["classes.id"],
            name="fk_exam_papers_class", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("max_marks > 0", name="ck_exam_papers_max_marks_positive"),
        sa.CheckConstraint(
            "pass_marks IS NULL OR (pass_marks >= 0 AND pass_marks <= max_marks)",
            name="ck_exam_papers_pass_within_max",
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR starts_at < ends_at",
            name="ck_exam_papers_times_ordered",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_exam_papers_tenant_id_id"),
    )
    op.create_index("idx_exam_papers_tenant", "exam_papers", ["tenant_id"])
    op.create_index(
        "idx_exam_papers_examination", "exam_papers", ["tenant_id", "examination_id"]
    )
    op.create_index("idx_exam_papers_class", "exam_papers", ["tenant_id", "class_id"])
    op.create_index("idx_exam_papers_date", "exam_papers", ["tenant_id", "exam_date"])
    op.create_index("idx_exam_papers_deleted_at", "exam_papers", ["deleted_at"])
    op.create_index(
        "uq_exam_papers_offering_component",
        "exam_papers",
        ["tenant_id", "examination_id", "class_subject_id", "component_label"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ----------------------------------------------------------------- marks
    op.create_table(
        "exam_marks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("exam_paper_id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="present"),
        sa.Column("marks_obtained", sa.Numeric(6, 2), nullable=True),
        sa.Column("remarks", sa.Text, nullable=True),
        sa.Column("entered_by_user_id", sa.String(36), nullable=True),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_exam_marks_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exam_paper_id"],
            ["exam_papers.tenant_id", "exam_papers.id"],
            name="fk_exam_marks_paper", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "student_id"],
            ["students.tenant_id", "students.id"],
            name="fk_exam_marks_student", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entered_by_user_id"], ["users.id"],
            name="fk_exam_marks_entered_by", ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('present', 'absent', 'exempted', 'malpractice')",
            name="ck_exam_marks_status",
        ),
        sa.CheckConstraint(
            "(status = 'present' AND marks_obtained IS NOT NULL) OR "
            "(status <> 'present' AND marks_obtained IS NULL)",
            name="ck_exam_marks_present_has_marks",
        ),
        sa.CheckConstraint(
            "marks_obtained IS NULL OR marks_obtained >= 0",
            name="ck_exam_marks_not_negative",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_exam_marks_tenant_id_id"),
    )
    op.create_index("idx_exam_marks_tenant", "exam_marks", ["tenant_id"])
    op.create_index("idx_exam_marks_student", "exam_marks", ["tenant_id", "student_id"])
    op.create_index("idx_exam_marks_deleted_at", "exam_marks", ["deleted_at"])
    op.create_index(
        "uq_exam_marks_paper_student",
        "exam_marks",
        ["tenant_id", "exam_paper_id", "student_id"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # --------------------------------------------------------------- results
    op.create_table(
        "exam_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("examination_id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("total_max", sa.Numeric(8, 2), nullable=True),
        sa.Column("total_obtained", sa.Numeric(8, 2), nullable=True),
        sa.Column("percentage", sa.Numeric(6, 3), nullable=True),
        sa.Column("grade_label", sa.String(40), nullable=True),
        sa.Column("is_pass", sa.Boolean, nullable=True),
        sa.Column("snapshot", sa.JSON, nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_user_id", sa.String(36), nullable=True),
        sa.Column("revision_reason", sa.Text, nullable=True),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_exam_results_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "examination_id"],
            ["examinations.tenant_id", "examinations.id"],
            name="fk_exam_results_examination", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "student_id"],
            ["students.tenant_id", "students.id"],
            name="fk_exam_results_student", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"], ["users.id"],
            name="fk_exam_results_published_by", ondelete="SET NULL",
        ),
        sa.CheckConstraint("version >= 1", name="ck_exam_results_version_positive"),
    )
    op.create_index("idx_exam_results_tenant", "exam_results", ["tenant_id"])
    op.create_index(
        "idx_exam_results_student", "exam_results", ["tenant_id", "student_id"]
    )
    op.create_index("idx_exam_results_deleted_at", "exam_results", ["deleted_at"])
    op.create_index(
        "uq_exam_results_current",
        "exam_results",
        ["tenant_id", "examination_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_exam_results_version",
        "exam_results",
        ["tenant_id", "examination_id", "student_id", "version"],
        unique=True,
    )

    # ------------------------------------------------------------- lifecycle
    op.create_table(
        "examination_lifecycle_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("examination_id", sa.String(36), nullable=False),
        sa.Column("event_name", sa.String(60), nullable=False),
        sa.Column("occurred_on", sa.Date, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_exam_lifecycle_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "examination_id"],
            ["examinations.tenant_id", "examinations.id"],
            name="fk_exam_lifecycle_examination", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"],
            name="fk_exam_lifecycle_actor", ondelete="SET NULL",
        ),
    )
    op.create_index(
        "idx_exam_lifecycle_examination",
        "examination_lifecycle_events",
        ["tenant_id", "examination_id"],
    )


def downgrade():
    op.drop_table("examination_lifecycle_events")
    op.drop_table("exam_results")
    op.drop_table("exam_marks")
    op.drop_table("exam_papers")
    op.drop_table("examinations")
    op.drop_table("grading_bands")
    op.drop_table("grading_schemes")
    op.drop_table("exam_types")
    op.drop_constraint("uq_students_tenant_id_id", "students", type_="unique")
