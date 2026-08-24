"""a document belongs to the person, and the store belongs to everyone

The constrain step of ADR-015, in two parts.

`student_documents` becomes `documents`, keyed to the human rather than to the
studentship that prompted collecting the paper, so a teacher who is also a
parent hands over their Aadhar once.

And the table is not a person's. A document names its owner as
(owner_kind, owner_id), so the examination module can file question papers and
answer sheets here without a migration or a second store. Storage keys are
tenant-scoped — {env}/tenants/{tenant}/{kind}/{owner}/... — so one school's
files are isolated by prefix and a school that leaves can be removed with one.

Ids are carried across unchanged. That is what makes `student_leaves`
survivable: its `attachment_document_id` keeps pointing at the same value, and
only the constraint underneath it has to move.

The type vocabulary is seeded with the rows that existed when this migration
was written, and is NOT imported from a catalogue module. A migration has to
mean the same thing in five years; importing something expected to grow would
make this step do something different on every future database. Later additions
arrive through the seed script.

Revision ID: 106_a_document_belongs_to_the_person
Revises: 105_a_sub_admin_keeps_the_classes_module
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "106_a_document_belongs_to_the_person"
down_revision = "105_a_sub_admin_keeps_the_classes_module"
branch_labels = None
depends_on = None

_PERSON = "person"

# (code, label, contexts, sequence, description)
_SEED_TYPES = [
    ("aadhar_card", "Aadhar Card", ["identity"], 10, ""),
    ("pan_card", "PAN Card", ["identity"], 20, ""),
    ("birth_certificate", "Birth Certificate", ["identity"], 30, ""),
    ("passport", "Passport", ["identity"], 40, ""),
    ("transfer_certificate", "Transfer Certificate", ["student"], 10,
     "Issued by the previous school on leaving."),
    ("leaving_certificate", "Leaving Certificate", ["student"], 20, ""),
    ("degree_certificate", "Degree Certificate", ["staff"], 10,
     "Highest qualification held."),
    ("experience_letter", "Experience Letter", ["staff"], 20,
     "Issued by a previous employer."),
    ("appointment_letter", "Appointment Letter", ["staff"], 30,
     "Issued by this school on joining."),
    ("employment_contract", "Employment Contract", ["staff"], 40, ""),
    ("police_verification", "Police Verification", ["staff"], 50,
     "Background check, required by several boards for staff working with children."),
    ("medical_fitness_certificate", "Medical Fitness Certificate", ["staff"], 60, ""),
    ("other", "Other", ["identity", "student", "staff"], 999, ""),
]

# Every v1 enum value is already a code above, so the copy is a straight move.
# Written out rather than defaulted, because "other" is the only safe fallback
# and a silent fallback would quietly relabel a real document.
_LEGACY_TYPES = {
    "aadhar_card",
    "birth_certificate",
    "leaving_certificate",
    "transfer_certificate",
    "passport",
    "other",
}

# The old keys were not tenant-scoped. They are carried across as they are: the
# bytes are where they are, and rewriting a key means copying every object in
# S3, which a schema migration must not be doing. New uploads land under the
# tenant prefix; old ones stay reachable by their stored key.
_COPY_DOCUMENTS = sa.text(
    """
    INSERT INTO documents (
        id, tenant_id, owner_kind, owner_id, document_type_code,
        original_filename, storage_key, mime_type, file_size_bytes,
        uploaded_by_user_id, created_at, updated_at
    )
    SELECT d.id,
           d.tenant_id,
           :owner_kind,
           s.person_id,
           d.document_type::text,
           d.original_filename,
           d.s3_object_key,
           d.mime_type,
           d.file_size_bytes,
           d.uploaded_by_user_id,
           d.created_at,
           d.updated_at
      FROM student_documents d
      JOIN students s ON s.id = d.student_id
    ON CONFLICT (id) DO NOTHING
    """
)


def _table_exists(bind, name: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :n"
            ),
            {"n": name},
        ).scalar()
    )


def _leave_attachment_fk(bind) -> str | None:
    """The auto-named FK 061 created without giving it a name."""
    return bind.execute(
        sa.text(
            """
            SELECT tc.constraint_name
              FROM information_schema.table_constraints tc
              JOIN information_schema.key_column_usage kcu
                ON kcu.constraint_name = tc.constraint_name
             WHERE tc.table_name = 'student_leaves'
               AND tc.constraint_type = 'FOREIGN KEY'
               AND kcu.column_name = 'attachment_document_id'
             LIMIT 1
            """
        )
    ).scalar()


def upgrade():
    bind = op.get_bind()

    op.create_table(
        "document_types",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("owner_kind", sa.String(40), nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("contexts", sa.JSON, nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False, server_default="100"),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_document_types_owner_kind", "document_types", ["owner_kind"])

    op.bulk_insert(
        sa.table(
            "document_types",
            sa.column("code", sa.String),
            sa.column("owner_kind", sa.String),
            sa.column("label", sa.Text),
            sa.column("contexts", sa.JSON),
            sa.column("sequence", sa.Integer),
            sa.column("description", sa.Text),
        ),
        [
            {
                "code": code,
                "owner_kind": _PERSON,
                "label": label,
                "contexts": contexts,
                "sequence": sequence,
                "description": description,
            }
            for code, label, contexts, sequence, description in _SEED_TYPES
        ],
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("owner_kind", sa.String(40), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("document_type_code", sa.String(64), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=False),
        sa.Column("uploaded_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_documents_tenant_id"
        ),
        sa.ForeignKeyConstraint(
            ["document_type_code"], ["document_types.code"],
            name="fk_documents_type", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"],
            name="fk_documents_uploaded_by", ondelete="SET NULL",
        ),
    )
    # There is deliberately no foreign key on (owner_kind, owner_id): the whole
    # point is that one table serves domains that have not been written yet, and
    # a polymorphic reference cannot be constrained. The registry's
    # resolve_tenant does that job on the way in, and delete_all_for on the way
    # out. Both are documented obligations of registering an owner kind.
    op.create_index("idx_documents_owner", "documents", ["owner_kind", "owner_id"])
    op.create_index(
        "idx_documents_owner_type",
        "documents",
        ["owner_kind", "owner_id", "document_type_code"],
    )
    op.create_index("idx_documents_uploaded_by", "documents", ["uploaded_by_user_id"])

    if not _table_exists(bind, "student_documents"):
        return

    unknown = (
        bind.execute(
            sa.text(
                "SELECT DISTINCT document_type::text FROM student_documents "
                "WHERE document_type::text <> ALL(:known)"
            ),
            {"known": list(_LEGACY_TYPES)},
        )
        .scalars()
        .all()
    )
    if unknown:
        raise RuntimeError(
            f"student_documents carries type(s) the catalogue does not name: "
            f"{', '.join(unknown)}. Add them to the seed above before moving the "
            "rows, or they land under a label nobody chose."
        )

    bind.execute(_COPY_DOCUMENTS, {"owner_kind": _PERSON})

    # Say so rather than assume it: students.person_id has been NOT NULL since
    # 084, so nothing should be left behind.
    stranded = bind.execute(
        sa.text(
            "SELECT count(*) FROM student_documents d "
            "WHERE NOT EXISTS (SELECT 1 FROM documents p WHERE p.id = d.id)"
        )
    ).scalar()
    if stranded:
        raise RuntimeError(
            f"{stranded} student document(s) did not move; their student has no "
            "person. Fix those rows before dropping the table, or the files "
            "become unreachable."
        )

    # The ids did not change, so the attachment column still points at the right
    # row — only the constraint under it moves.
    existing_fk = _leave_attachment_fk(bind)
    if existing_fk:
        op.drop_constraint(existing_fk, "student_leaves", type_="foreignkey")
    op.create_foreign_key(
        "fk_student_leaves_attachment_document",
        "student_leaves",
        "documents",
        ["attachment_document_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_table("student_documents")


def downgrade():
    # Deliberately not reversible past the data move. Recreating
    # student_documents is straightforward, but a document owned by a person who
    # is not a student — or by an exam paper — has no student to be given back
    # to, and inventing one would put a row in a table the school never made.
    raise NotImplementedError(
        "106 is not reversible: documents with no studentship have no "
        "student_documents row to return to. Restore from a backup instead."
    )
