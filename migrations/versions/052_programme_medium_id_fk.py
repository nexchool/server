"""Add academic_programmes.medium_id FK to mediums; backfill from medium string.

Revision ID: 052_programme_medium_id_fk
Revises: 051_drop_subject_templates
Create Date: 2026-05-05

Forward-only data shaping; the legacy `academic_programmes.medium` string is
kept in place for back-compat and is mirrored on writes for one release.
Subject contexts (`subject_contexts.medium_id`) become the single source of
truth, but programme-level medium remains queryable via the new FK.
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


revision = "052_programme_medium_id_fk"
down_revision = "051_drop_subject_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "academic_programmes",
        sa.Column("medium_id", sa.String(length=36), nullable=True),
    )

    conn = op.get_bind()

    # Preload existing mediums per (tenant, lower-name) for matching.
    existing_rows = conn.execute(
        sa.text(
            "SELECT id, tenant_id, name FROM mediums WHERE deleted_at IS NULL"
        )
    ).fetchall()
    seen = {(r[1], (r[2] or "").strip().lower()): r[0] for r in existing_rows}

    programmes = conn.execute(
        sa.text(
            "SELECT id, tenant_id, medium FROM academic_programmes "
            "WHERE medium IS NOT NULL AND medium <> ''"
        )
    ).fetchall()

    for pid, tid, medium in programmes:
        key = (tid, medium.strip().lower())
        medium_id = seen.get(key)
        if not medium_id:
            medium_id = str(uuid.uuid4())
            conn.execute(
                sa.text(
                    "INSERT INTO mediums (id, tenant_id, name, is_active, created_at, updated_at) "
                    "VALUES (:id, :tid, :name, TRUE, now(), now())"
                ),
                {"id": medium_id, "tid": tid, "name": medium.strip()},
            )
            seen[key] = medium_id
        conn.execute(
            sa.text(
                "UPDATE academic_programmes SET medium_id = :mid WHERE id = :pid"
            ),
            {"mid": medium_id, "pid": pid},
        )

    op.create_foreign_key(
        "fk_academic_programmes_medium_id",
        "academic_programmes",
        "mediums",
        ["medium_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_academic_programmes_medium_id",
        "academic_programmes",
        ["medium_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_academic_programmes_medium_id",
        table_name="academic_programmes",
    )
    op.drop_constraint(
        "fk_academic_programmes_medium_id",
        "academic_programmes",
        type_="foreignkey",
    )
    op.drop_column("academic_programmes", "medium_id")
