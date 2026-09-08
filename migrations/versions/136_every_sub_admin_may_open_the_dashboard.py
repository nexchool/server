"""Every sub-admin may open the dashboard.

`GET /api/dashboard/` is guarded by `dashboard.read`. That permission is
granted to the `Admin` role and to nothing else, and no module in
`modules/sub_admins/catalog.py` ever granted it — so every sub-admin a School
Admin has created until now receives a 403 on the screen the app opens on,
while the sidebar shows them the link because `/dashboard` is one of the few
entries with no gate. A finance officer could reach `/finance` by typing it
and could not reach the landing page.

`BASELINE_PERMISSIONS` fixes that going forward: `expand_selection` now adds
`dashboard.read` to any non-empty selection. But sub-admin authority is stored
as `RolePermission` rows on a private `subadmin:<user_id>` role, written when
the School Admin last saved that sub-admin — nothing recomputes it on login.
So the fix reaches nobody who already exists until someone opens and re-saves
each of them one at a time. This migration is that re-save.

**It is safe to hand out only because the dashboard now composes itself per
caller.** `modules/dashboard/service.py` scopes every section against the
caller's permissions, so a warden holding `dashboard.read` receives the
sections they may act on and `{"visible": false}` for the rest — the school's
finance position is not in their payload at all. Granting this before that
composition existed would have been a leak; the two ship together, and this
migration must not be applied to a deployment whose code predates it.

Scope is deliberately narrow: roles with `is_subadmin = true` that already
hold at least one permission. A sub-admin mid-creation with an empty role gets
nothing, matching `expand_selection([])`, and no other role is touched.

The downgrade removes exactly the rows this added — `dashboard.read` on
sub-admin roles — and leaves the `Admin` role's own grant alone.
"""

from alembic import op
import sqlalchemy as sa

revision = "136_every_sub_admin_may_open_the_dashboard"
down_revision = "135_a_school_may_be_configured_for_whatsapp"
branch_labels = None
depends_on = None


PERMISSION_NAME = "dashboard.read"


def upgrade():
    conn = op.get_bind()

    permission_id = conn.execute(
        sa.text("SELECT id FROM permissions WHERE name = :name"),
        {"name": PERMISSION_NAME},
    ).scalar()

    # The permission is seeded from the RBAC catalogue on boot. If this runs on
    # a database that has never booted the app (a fresh CI schema, say) there is
    # nothing to grant against and nothing to fix — the seeder will do it.
    if permission_id is None:
        return

    # `id` and `created_at` are NOT NULL and their defaults live in Python
    # (`default=lambda: str(uuid.uuid4())`, `default=utc_now`), not in the
    # schema — a bare INSERT of the three business columns fails. SQL has to
    # supply both, which is why this is not the obvious three-column insert.
    #
    # `role_permissions` is tenant-scoped, so the tenant is copied from the role
    # rather than guessed. `NOT EXISTS` keeps this re-runnable.
    conn.execute(
        sa.text(
            """
            INSERT INTO role_permissions
                (id, tenant_id, role_id, permission_id, created_at)
            SELECT gen_random_uuid()::text, r.tenant_id, r.id, :permission_id, now()
            FROM roles r
            WHERE r.is_subadmin = true
              AND EXISTS (
                    SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id
              )
              AND NOT EXISTS (
                    SELECT 1 FROM role_permissions rp
                    WHERE rp.role_id = r.id AND rp.permission_id = :permission_id
              )
            """
        ),
        {"permission_id": permission_id},
    )


def downgrade():
    conn = op.get_bind()

    permission_id = conn.execute(
        sa.text("SELECT id FROM permissions WHERE name = :name"),
        {"name": PERMISSION_NAME},
    ).scalar()
    if permission_id is None:
        return

    conn.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            WHERE permission_id = :permission_id
              AND role_id IN (SELECT id FROM roles WHERE is_subadmin = true)
            """
        ),
        {"permission_id": permission_id},
    )
