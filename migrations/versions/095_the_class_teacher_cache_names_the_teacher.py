"""The class-teacher cache names the teacher, not their login.

ADR-014 ratified ``classes.teacher_id`` as a permanent performance cache of
the class-teacher responsibility owned by ``class_teacher_assignments``. But
the cache was keyed on ``users.id`` — a login — so an account-less teacher
could not be cached at all, and every reader had to hop through
``teachers.user_id`` before it could compare anything.

Three steps, in order:

1. **Owner rows first.** For years ``create_class`` wrote the cache without
   the owner row, so a class could have a cached class teacher that
   ``class_teacher_assignments`` knew nothing about. Every such class gets an
   active primary assignment now, with ``allow_attendance_marking`` on —
   because the legacy attendance path those teachers relied on granted
   marking, and this migration is what retires that path.

2. **Re-key the cache**: ``users.id`` becomes ``teachers.id`` via
   ``teachers.user_id``. A cached login with no teacher row means there is no
   class teacher; it becomes NULL.

3. **The FK moves to** ``teachers(id) ON DELETE SET NULL`` — which also
   repairs migration 018, which recreated the users FK without any ondelete
   and left teacher deletion needing hand-written detach code.

Revision ID: 095_the_class_teacher_cache_names_the_teacher
Revises: 094_login_is_optional
"""

import sqlalchemy as sa
from alembic import op

revision = "095_the_class_teacher_cache_names_the_teacher"
down_revision = "094_login_is_optional"
branch_labels = None
depends_on = None


_OWNER_ROWS_FOR_CACHE_ONLY_CLASS_TEACHERS = """
INSERT INTO class_teacher_assignments (
    id, tenant_id, class_id, teacher_id, role, allow_attendance_marking,
    is_active, created_at, updated_at
)
SELECT
    md5('cta-from-cache:' || c.id)::uuid::text,
    c.tenant_id,
    c.id,
    t.id,
    'primary',
    TRUE,
    TRUE,
    NOW(),
    NOW()
FROM classes c
JOIN teachers t
  ON t.user_id = c.teacher_id AND t.tenant_id = c.tenant_id
WHERE c.teacher_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM class_teacher_assignments cta
      WHERE cta.tenant_id = c.tenant_id
        AND cta.class_id = c.id
        AND cta.role = 'primary'
        AND cta.is_active
        AND cta.deleted_at IS NULL
  )
"""

_REKEY_TO_TEACHER = """
UPDATE classes c
SET teacher_id = t.id
FROM teachers t
WHERE t.user_id = c.teacher_id AND t.tenant_id = c.tenant_id
"""

_CLEAR_UNRESOLVABLE = """
UPDATE classes c
SET teacher_id = NULL
WHERE c.teacher_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM teachers t WHERE t.id = c.teacher_id)
"""


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text(_OWNER_ROWS_FOR_CACHE_ONLY_CLASS_TEACHERS))

    # The users FK must go before the re-key writes teacher ids into the
    # column. (018 recreated it unnamed; Postgres gave it the default name.)
    op.execute("ALTER TABLE classes DROP CONSTRAINT IF EXISTS classes_teacher_id_fkey")

    bind.execute(sa.text(_REKEY_TO_TEACHER))
    bind.execute(sa.text(_CLEAR_UNRESOLVABLE))

    op.create_foreign_key(
        "fk_classes_teacher_id_teachers",
        "classes",
        "teachers",
        ["teacher_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_classes_teacher_id_teachers", "classes", type_="foreignkey")

    # Back to login keys. An account-less teacher has no login to key on, so
    # their class loses its cache — the owner row keeps the truth.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE classes c
            SET teacher_id = t.user_id
            FROM teachers t
            WHERE t.id = c.teacher_id
            """
        )
    )
    bind.execute(sa.text(_CLEAR_UNRESOLVABLE.replace("FROM teachers t", "FROM users t")))

    # Restore the FK exactly as 018 left it: users(id), no ondelete.
    op.create_foreign_key(
        "classes_teacher_id_fkey", "classes", "users", ["teacher_id"], ["id"]
    )
