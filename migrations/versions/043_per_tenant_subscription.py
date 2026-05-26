"""Per-tenant subscription model: pricing, discount, and feature flags on tenants.

Adds:
  - tenants.price_per_student_per_year   numeric(12,2) nullable
  - tenants.discount_percentage          numeric(5,2)  nullable
  - tenants.discount_start_date          date          nullable
  - tenants.discount_end_date            date          nullable
  - tenants.feature_flags                json          NOT NULL default {}

Backfills `feature_flags` for each existing tenant by copying the boolean
keys from `plans.features_json` of its current plan. Missing keys default
to True (enabled). Tenants with no plan get all-enabled flags.

`plans` and `tenants.plan_id` are intentionally retained — they are removed
in a later migration once the application no longer references them.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


revision = "043_per_tenant_subscription"
down_revision = "042_student_academic_result"
branch_labels = None
depends_on = None


# Mirrors core.feature_flags.OPTIONAL_FEATURES at the time of this migration.
# Hard-coded so this migration is reproducible if the constant changes later.
OPTIONAL_FEATURES = [
    "attendance",
    "fees_management",
    "finance",
    "timetable",
    "schedule_management",
    "transport",
    "notifications",
    "holiday_management",
    "library",
    "hostel",
    "inventory",
    "examinations",
    "reports",
    "search",
    "academics_advanced",
    "student_management",
    "teacher_management",
    "class_management",
]


def upgrade():
    op.add_column(
        "tenants",
        sa.Column("price_per_student_per_year", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("discount_percentage", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("discount_start_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("discount_end_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("feature_flags", JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )

    # Backfill: copy each tenant's plan.features_json (if any) into tenants.feature_flags.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT t.id, p.features_json "
            "FROM tenants t LEFT JOIN plans p ON p.id = t.plan_id"
        )
    ).fetchall()

    for row in rows:
        tenant_id = row[0]
        plan_features = row[1] or {}
        flags = {}
        for key in OPTIONAL_FEATURES:
            value = plan_features.get(key) if isinstance(plan_features, dict) else None
            flags[key] = True if value is None else bool(value)
        bind.execute(
            sa.text("UPDATE tenants SET feature_flags = CAST(:flags AS json) WHERE id = :id"),
            {"flags": _json_dumps(flags), "id": tenant_id},
        )


def downgrade():
    op.drop_column("tenants", "feature_flags")
    op.drop_column("tenants", "discount_end_date")
    op.drop_column("tenants", "discount_start_date")
    op.drop_column("tenants", "discount_percentage")
    op.drop_column("tenants", "price_per_student_per_year")


def _json_dumps(obj):
    import json
    return json.dumps(obj)
