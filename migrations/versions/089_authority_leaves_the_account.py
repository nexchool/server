"""Authority leaves the account: retire user_roles

Authority is held by a person's employment, not by their login (ADR-013).
Every reader and writer now goes through the Authorization Domain, so the
assignment table on the account has nothing left to answer.

This migration carries any assignment that still means something onto the
employment that should hold it, and refuses to run if it finds one it can
neither carry nor prove redundant — losing an assignment silently means
somebody cannot sign in on Monday morning, and the school finds out before
we do.

Two kinds of assignment are deliberately not carried:

  * Platform administrators run Nexchool rather than working at a school.
    They bypass tenant authorization entirely, so an employment would be a
    fiction invented to satisfy a foreign key.
  * Students. A student was never granted the right to see their own
    attendance — it follows from being a student, and is derived from the
    relationship now. Their assignment is redundant, which this migration
    verifies permission by permission before dropping it.

Revision ID: 089_authority_leaves_the_account
Revises: 088_authority_stays_in_its_organization
"""
from alembic import op
import sqlalchemy as sa


revision = "089_authority_leaves_the_account"
down_revision = "088_authority_stays_in_its_organization"
branch_labels = None
depends_on = None


RELATIONSHIP_STUDENT = "student"


# Holders that still work here but were never recorded as employed: accounts
# created before employment was a thing the system knew about.
_EMPLOY_UNRECORDED_HOLDERS = sa.text(
    """
    INSERT INTO staff (id, tenant_id, person_id, employment_status,
                       created_at, updated_at)
    SELECT DISTINCT ON (ur.tenant_id, u.person_id)
           -- Derived from the person and tenant, not generated: it has to fit
           -- varchar(36), and a re-run must not open a second employment for
           -- someone who already has one.
           md5('staff:' || ur.tenant_id || ':' || u.person_id)::uuid::text,
           ur.tenant_id, u.person_id, 'working', now(), now()
      FROM user_roles ur
      JOIN users u ON u.id = ur.user_id
     WHERE COALESCE(u.is_platform_admin, false) = false
       AND u.person_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM staff s
                        WHERE s.person_id = u.person_id
                          AND s.tenant_id = ur.tenant_id)
       AND NOT EXISTS (SELECT 1 FROM students st
                        WHERE st.person_id = u.person_id
                          AND st.tenant_id = ur.tenant_id)
    """
)

# An employment covers a period, so one that begins must be open.
_OPEN_THEIR_EMPLOYMENT = sa.text(
    """
    INSERT INTO staff_employment_periods (id, tenant_id, staff_id,
                                          created_at, updated_at)
    SELECT md5('period:' || s.id)::uuid::text,
           s.tenant_id, s.id, now(), now()
      FROM staff s
     WHERE NOT EXISTS (SELECT 1 FROM staff_employment_periods p
                        WHERE p.staff_id = s.id)
    """
)

_CARRY_AUTHORITY_ONTO_EMPLOYMENT = sa.text(
    """
    INSERT INTO staff_authorities (id, tenant_id, staff_id, role_id, granted_at)
    SELECT DISTINCT ON (s.id, ur.role_id)
           md5('authority:' || s.id || ':' || ur.role_id)::uuid::text,
           ur.tenant_id, s.id, ur.role_id, now()
      FROM user_roles ur
      JOIN users u ON u.id = ur.user_id
      JOIN staff s ON s.person_id = u.person_id AND s.tenant_id = ur.tenant_id
     WHERE COALESCE(u.is_platform_admin, false) = false
       AND NOT EXISTS (SELECT 1 FROM staff_authorities held
                        WHERE held.staff_id = s.id
                          AND held.role_id = ur.role_id)
    """
)

# Anything left: not carried, not a platform admin, and — for a student — not
# already covered by the access being a student implies.
_ASSIGNMENTS_THAT_WOULD_BE_LOST = sa.text(
    """
    SELECT u.email, r.name
      FROM user_roles ur
      JOIN users u ON u.id = ur.user_id
      JOIN roles r ON r.id = ur.role_id
      LEFT JOIN staff s ON s.person_id = u.person_id AND s.tenant_id = ur.tenant_id
      LEFT JOIN staff_authorities held
             ON held.staff_id = s.id AND held.role_id = ur.role_id
     WHERE COALESCE(u.is_platform_admin, false) = false
       AND held.id IS NULL
       AND EXISTS (
             SELECT 1 FROM role_permissions rp
              WHERE rp.role_id = ur.role_id
                AND rp.permission_id NOT IN (
                      SELECT implied.permission_id
                        FROM role_permissions implied
                        JOIN roles ir ON ir.id = implied.role_id
                       WHERE ir.tenant_id = ur.tenant_id
                         AND ir.implied_by_relationship = :relationship
                    )
           )
     LIMIT 20
    """
)


def upgrade():
    bind = op.get_bind()

    bind.execute(_EMPLOY_UNRECORDED_HOLDERS)
    bind.execute(_OPEN_THEIR_EMPLOYMENT)
    bind.execute(_CARRY_AUTHORITY_ONTO_EMPLOYMENT)

    stranded = bind.execute(
        _ASSIGNMENTS_THAT_WOULD_BE_LOST, {"relationship": RELATIONSHIP_STUDENT}
    ).fetchall()
    if stranded:
        listed = ", ".join(f"{email} ({role})" for email, role in stranded)
        raise RuntimeError(
            "Refusing to drop user_roles: these assignments would lose access "
            f"and no employment or relationship accounts for them — {listed}. "
            "Record the employment these people hold, then run this again."
        )

    op.drop_table("user_roles")


def downgrade():
    op.create_table(
        "user_roles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("role_id", sa.String(length=36), nullable=False, index=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            name="fk_user_roles_role_same_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id", "role_id", "tenant_id", name="uq_user_role_tenant"
        ),
    )
    # The table comes back empty on purpose. Authority has been held by the
    # employment since the upgrade, so refilling this from staff_authorities
    # would assert that accounts hold rights they do not.
