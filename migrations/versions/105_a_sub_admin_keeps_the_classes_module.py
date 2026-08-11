"""A sub-admin who manages classes can read the structure a class sits in.

The Classes module in the sub-admin catalogue granted `class.read` /
`class.manage` and none of the structural reads. A class sits in a campus, on a
programme, at a grade, so the classes screen rendered with every filter empty
and the add-a-section form could never be completed — the campus, programme and
grade queries all answered 403.

The catalogue now includes `school_unit.read`, `programme.read` and
`grade.read` at both levels. That fixes sub-admins created from now on. This
fixes the ones that already exist, and it has to be a migration rather than a
note in a runbook, because leaving it undone is worse than it looks:

`summarize_permissions` reverse-maps a private role back into module levels by
finding the highest level whose permissions are **all** present. An existing
sub-admin holding only `class.manage` now satisfies neither level, so Classes
disappears from their summary entirely — the detail screen shows no Classes
access, and an administrator who edits anything else about that sub-admin
submits that summary back and silently revokes what they had.

Additive only: a role that never had class access is left alone.

Revision ID: 105_a_sub_admin_keeps_the_classes_module
Revises: 104_a_merge_records_who_and_why
"""

import sqlalchemy as sa
from alembic import op

revision = "105_a_sub_admin_keeps_the_classes_module"
down_revision = "104_a_merge_records_who_and_why"
branch_labels = None
depends_on = None

STRUCTURAL_READS = ("school_unit.read", "programme.read", "grade.read")

# Private sub-admin roles are named `subadmin:<user id>`; the four default roles
# are handled by the catalogue and the seeder, not here.
_GRANT = sa.text(
    """
    INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at)
    SELECT gen_random_uuid()::text, r.tenant_id, r.id, needed.id, now()
    FROM roles r
    JOIN role_permissions held ON held.role_id = r.id
    JOIN permissions class_perm ON class_perm.id = held.permission_id
    CROSS JOIN permissions needed
    WHERE r.name LIKE 'subadmin:%'
      AND class_perm.name IN ('class.read', 'class.manage')
      AND needed.name = :permission
      AND NOT EXISTS (
          SELECT 1 FROM role_permissions existing
          WHERE existing.role_id = r.id AND existing.permission_id = needed.id
      )
    """
)


def upgrade():
    bind = op.get_bind()
    for permission in STRUCTURAL_READS:
        bind.execute(_GRANT, {"permission": permission})


def downgrade():
    # Deliberately not reversed. These reads are what make the classes screen
    # usable, and a sub-admin may also hold them from another module — taking
    # them back would break screens this migration never touched.
    pass
