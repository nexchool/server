"""Authority stays in its organization — the rows migration 088 could not reach.

Migration 088 made it impossible for an authority row in one school to name a
Role belonging to another, by adding composite `(tenant_id, role_id)` foreign
keys against `uq_roles_tenant_id_id`. It covered `user_roles` (since dropped),
`role_permissions` and `staff_authorities`.

It missed `authority_delegations`, which had been created two migrations
earlier — the table that lends one employment's authority to another. A
delegation is exactly where a cross-tenant reference would be most valuable to
an attacker and least visible to a reviewer: the row looks ordinary, and
nothing reads it outside its date window, so it would sit unnoticed until the
day it applied.

It also left the *employment* side unguarded everywhere: `staff` had no
`UNIQUE (tenant_id, id)`, so no composite FK could point at it at all. Authority
is held by an employment (ADR-013), so "authority stays in its organization"
is only enforced once both halves — the Role and the Staff — are pinned.

No data changes: every existing row was verified consistent before this ran.

Revision ID: 097_authority_stays_part_two
Revises: 096_one_timetable
"""

import sqlalchemy as sa
from alembic import op

revision = "097_authority_stays_part_two"
down_revision = "096_one_timetable"
branch_labels = None
depends_on = None


# (label, child table, child tenant col, child fk col, parent table)
_GUARDS = [
    ("fk_authority_delegations_role_within_tenant", "authority_delegations", "role_id", "roles"),
    ("fk_authority_delegations_from_staff_within_tenant", "authority_delegations", "from_staff_id", "staff"),
    ("fk_authority_delegations_to_staff_within_tenant", "authority_delegations", "to_staff_id", "staff"),
    ("fk_staff_authorities_staff_within_tenant", "staff_authorities", "staff_id", "staff"),
]


def _refuse_if_already_crossed(bind):
    """A composite FK cannot be added over rows that already violate it.

    Reported rather than silently repaired: a cross-tenant authority row is a
    security finding, and someone has to look at it before it disappears.
    """
    for _name, child, column, parent in _GUARDS:
        crossed = bind.execute(
            sa.text(
                f"SELECT COUNT(*) FROM {child} c JOIN {parent} p ON p.id = c.{column} "
                "WHERE c.tenant_id IS DISTINCT FROM p.tenant_id"
            )
        ).scalar()
        if crossed:
            raise RuntimeError(
                f"{crossed} row(s) in {child}.{column} reference a {parent} row "
                "owned by a different organization. Investigate before adding "
                "the constraint — these rows grant authority across tenants."
            )


def upgrade():
    bind = op.get_bind()
    _refuse_if_already_crossed(bind)

    # A composite FK needs a matching unique on the parent. `roles` got one in
    # 088; `staff` never had one, which is why the employment side of every
    # authority row has been unguarded until now.
    op.create_unique_constraint("uq_staff_tenant_id_id", "staff", ["tenant_id", "id"])

    for name, child, column, parent in _GUARDS:
        op.create_foreign_key(
            name,
            child,
            parent,
            ["tenant_id", column],
            ["tenant_id", "id"],
            ondelete="CASCADE",
        )


def downgrade():
    for name, child, _column, _parent in _GUARDS:
        op.drop_constraint(name, child, type_="foreignkey")
    op.drop_constraint("uq_staff_tenant_id_id", "staff", type_="unique")
