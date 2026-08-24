"""a stream is something a school defines, not something we ship

`classes.stream` was free text guarded by a CHECK constraint naming four
tracks, with the same four repeated as a Python frozenset in
`school_setup/bulk_generator_service.py`. A school offering "Integrated
Science" needed a migration *and* a deploy, which is the "configuration, not
forks" rule broken in two places at once.

It also could not work. `stream` was absent from
`uq_classes_unit_programme_grade_section_year`, so Grade 11 Science A and
Grade 11 Commerce A — both section "A" — collided on insert. The parser in the
bulk generator read "Sci-A" into (stream, section) and the constraint underneath
refused to store the result. No live row has ever carried a stream, so the path
was never exercised.

Identity therefore becomes two partial unique indexes rather than one
constraint. Postgres treats NULLs as distinct, so a single index over a
nullable `stream_id` would stop protecting the streamless classes that are
almost all of them. The pair keeps the old rule exactly where it applied and
adds the new one only where a stream exists.

The four common tracks are seeded per tenant so a school that opens Grade 11
finds them already there. They are written out here rather than imported: a
migration has to mean the same thing in five years, and a catalogue expected to
grow would make this step do something different on every future database.

Revision ID: 107_a_stream_is_a_domain_entity
Revises: 106_a_document_belongs_to_the_person
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "107_a_stream_is_a_domain_entity"
down_revision = "106_a_document_belongs_to_the_person"
branch_labels = None
depends_on = None

_OLD_UNIQUE = "uq_classes_unit_programme_grade_section_year"
_IDENTITY_COLUMNS = [
    "tenant_id",
    "school_unit_id",
    "programme_id",
    "grade_id",
    "section",
    "academic_year_id",
]

# (name, code, sequence)
_SEED_STREAMS = [
    ("Science", "SCI", 10),
    ("Commerce", "COM", 20),
    ("Arts", "ART", 30),
    ("Vocational", "VOC", 40),
]

# Derived from the rows they describe, never gen_random_uuid(): length is then
# guaranteed to fit varchar(36) and a re-run cannot duplicate.
_SEED_PER_TENANT = sa.text(
    """
    INSERT INTO streams (id, tenant_id, name, code, sequence, created_at, updated_at)
    SELECT md5('stream:' || t.id || ':' || :name)::uuid::text,
           t.id, :name, :code, :sequence, now(), now()
      FROM tenants t
    ON CONFLICT DO NOTHING
    """
)

# Any value a school actually typed is carried, even though no live row has
# one. A migration that assumes its own audit was right is how data goes
# missing.
_CARRY_EXISTING = sa.text(
    """
    INSERT INTO streams (id, tenant_id, name, code, sequence, created_at, updated_at)
    SELECT DISTINCT md5('stream:' || c.tenant_id || ':' || c.stream)::uuid::text,
           c.tenant_id, c.stream, NULL, 900, now(), now()
      FROM classes c
     WHERE c.stream IS NOT NULL AND c.stream <> ''
    ON CONFLICT DO NOTHING
    """
)

_LINK_EXISTING = sa.text(
    """
    UPDATE classes c
       SET stream_id = s.id
      FROM streams s
     WHERE s.tenant_id = c.tenant_id
       AND s.name = c.stream
       AND c.stream IS NOT NULL AND c.stream <> ''
    """
)


def _constraint_exists(bind, table: str, name: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.table_constraints "
                "WHERE table_name = :t AND constraint_name = :n"
            ),
            {"t": table, "n": name},
        ).scalar()
    )


def upgrade():
    bind = op.get_bind()

    op.create_table(
        "streams",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("code", sa.String(32), nullable=True),
        sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_streams_tenant_id", ondelete="CASCADE",
        ),
    )
    op.create_index("idx_streams_sequence", "streams", ["sequence"])
    op.create_index("idx_streams_deleted_at", "streams", ["deleted_at"])
    op.create_index(
        "uq_streams_tenant_name_active",
        "streams",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_streams_tenant_code_active",
        "streams",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("code IS NOT NULL AND deleted_at IS NULL"),
    )
    # Lets a later migration declare a composite FK (tenant_id, stream_id), the
    # guard 088/097 established for cross-tenant references.
    op.create_unique_constraint(
        "uq_streams_tenant_id_id", "streams", ["tenant_id", "id"]
    )

    for name, code, sequence in _SEED_STREAMS:
        bind.execute(_SEED_PER_TENANT, {"name": name, "code": code, "sequence": sequence})

    op.add_column("classes", sa.Column("stream_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_classes_stream_id", "classes", "streams",
        ["stream_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("idx_classes_stream_id", "classes", ["stream_id"])

    bind.execute(_CARRY_EXISTING)
    bind.execute(_LINK_EXISTING)

    stranded = bind.execute(
        sa.text(
            "SELECT count(*) FROM classes "
            "WHERE stream IS NOT NULL AND stream <> '' AND stream_id IS NULL"
        )
    ).scalar()
    if stranded:
        raise RuntimeError(
            f"{stranded} class(es) name a stream that could not be carried into "
            "the streams table. Inspect classes.stream before dropping it."
        )

    # The CHECK named the four tracks in the database, so it has to go with the
    # column it guarded — leaving it would refuse a school its own vocabulary.
    if _constraint_exists(bind, "classes", "ck_classes_stream"):
        op.drop_constraint("ck_classes_stream", "classes", type_="check")
    op.drop_column("classes", "stream")

    # Identity: the old rule where no stream is named, the widened rule where
    # one is. Two indexes rather than one over a nullable column, because
    # Postgres would treat every NULL stream as distinct and stop protecting
    # the streamless classes entirely.
    if _constraint_exists(bind, "classes", _OLD_UNIQUE):
        op.drop_constraint(_OLD_UNIQUE, "classes", type_="unique")
    op.create_index(
        "uq_classes_identity_no_stream",
        "classes",
        _IDENTITY_COLUMNS,
        unique=True,
        postgresql_where=sa.text("stream_id IS NULL"),
    )
    op.create_index(
        "uq_classes_identity_with_stream",
        "classes",
        _IDENTITY_COLUMNS + ["stream_id"],
        unique=True,
        postgresql_where=sa.text("stream_id IS NOT NULL"),
    )


def downgrade():
    bind = op.get_bind()

    op.add_column("classes", sa.Column("stream", sa.String(20), nullable=True))
    bind.execute(
        sa.text(
            "UPDATE classes c SET stream = s.name FROM streams s "
            "WHERE s.id = c.stream_id"
        )
    )

    op.drop_index("uq_classes_identity_with_stream", table_name="classes")
    op.drop_index("uq_classes_identity_no_stream", table_name="classes")
    op.create_unique_constraint(_OLD_UNIQUE, "classes", _IDENTITY_COLUMNS)

    # Only restore the CHECK if the data can satisfy it — a school that took up
    # the freedom this migration granted has streams the old rule refused.
    unnameable = bind.execute(
        sa.text(
            "SELECT count(*) FROM classes WHERE stream IS NOT NULL AND stream "
            "NOT IN ('Science', 'Commerce', 'Arts', 'Vocational')"
        )
    ).scalar()
    if not unnameable:
        op.create_check_constraint(
            "ck_classes_stream",
            "classes",
            "stream IS NULL OR stream IN "
            "('Science', 'Commerce', 'Arts', 'Vocational')",
        )

    op.drop_index("idx_classes_stream_id", table_name="classes")
    op.drop_constraint("fk_classes_stream_id", "classes", type_="foreignkey")
    op.drop_column("classes", "stream_id")
    op.drop_table("streams")
