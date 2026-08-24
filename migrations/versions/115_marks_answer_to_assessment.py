"""the marks namespace stops being one letter from the grade master

`grades.*` was seeded for a marks feature nobody built: six keys, granted to
Admin, Teacher and Student, and **enforced nowhere** — verified across the
whole server. The live grade *master* — Std 10, Grade 1 — answers to
`grade.read` / `grade.manage`.

One letter apart, and `has_permission` resolves `<resource>.manage` over any
`<resource>.*` on the string prefix. So `grades.manage` and `grade.manage` are
entirely different authorities that look identical in review, and a typo is
either a silent grant or a permanent silent 403 that the key-existence test
cannot catch, because both keys exist.

Renamed to `assessment.*` before Examination puts weight on it. The revoke is
the load-bearing half: `seed_roles_for_tenant` only ever ADDS, so removing a
key from the catalogue changes nothing anywhere until a migration takes it
away — the lesson migration 103 recorded.

`grade.*` is untouched.

Revision ID: 115_marks_answer_to_assessment
Revises: 114_an_examination_is_an_event_with_papers
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "115_marks_answer_to_assessment"
down_revision = "114_an_examination_is_an_event_with_papers"
branch_labels = None
depends_on = None

# old key -> (new key, description)
_RENAMES = {
    "grades.read.self": ("assessment.read.self", "View own marks and results"),
    "grades.read.class": ("assessment.read.class", "View marks for own classes"),
    "grades.read.all": ("assessment.read.all", "View all marks and results"),
    "grades.create": ("assessment.enter", "Enter marks"),
    "grades.update": ("assessment.update", "Correct marks"),
    "grades.manage": ("assessment.manage", "Full assessment access"),
}

# Renaming the permission row itself carries every grant with it, because
# role_permissions references permissions.id. That is one UPDATE rather than a
# grant-and-revoke dance, and it cannot drop a role's authority halfway.
_RENAME = sa.text(
    "UPDATE permissions SET name = :new, description = :description "
    "WHERE name = :old"
)

# Any tenant that already had the new name (a reseed against a newer catalogue)
# would collide with the rename, so those old rows are dropped instead —
# grants and all, since they duplicate authority the new key already carries.
_DROP_GRANTS = sa.text(
    "DELETE FROM role_permissions WHERE permission_id IN "
    "(SELECT id FROM permissions WHERE name = :old)"
)
_DROP_PERMISSION = sa.text("DELETE FROM permissions WHERE name = :old")


def _exists(bind, name: str) -> bool:
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM permissions WHERE name = :n LIMIT 1"), {"n": name}
        ).scalar()
    )


def upgrade():
    bind = op.get_bind()

    for old, (new, description) in _RENAMES.items():
        if not _exists(bind, old):
            continue
        if _exists(bind, new):
            bind.execute(_DROP_GRANTS, {"old": old})
            bind.execute(_DROP_PERMISSION, {"old": old})
            continue
        bind.execute(_RENAME, {"old": old, "new": new, "description": description})

    left = bind.execute(
        sa.text("SELECT count(*) FROM permissions WHERE name LIKE 'grades.%'")
    ).scalar()
    if left:
        raise RuntimeError(
            f"{left} 'grades.*' permission(s) survived the rename. They are one "
            "letter from the live 'grade.*' master and must not both exist."
        )


def downgrade():
    bind = op.get_bind()
    for old, (new, _description) in _RENAMES.items():
        if _exists(bind, new) and not _exists(bind, old):
            bind.execute(
                sa.text("UPDATE permissions SET name = :old WHERE name = :new"),
                {"old": old, "new": new},
            )
