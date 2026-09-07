"""What a school pays for, and what it costs us.

NexSchool has always billed one thing — students, once a year, at one rate.
That model has no room for a service bought by the unit from somebody else,
and OTP is about to be the first of those: a provider charges NexSchool per
message, NexSchool may charge the school something different, and the two
numbers have to be able to move independently.

Four tables, in the order the money moves:

    service_providers      the vendor
    provider_services      what NexSchool buys from them, and by what unit
    tenant_services        this school uses that, at these prices
    service_usage_records  this much was used, this once

The catalog (the first two) is global — which vendor NexSchool uses is not a
per-school setting. The last two are tenant-owned and carry `tenant_id`.

Purely additive. Nothing existing is altered, nothing is backfilled, and no
school is enrolled in anything: a tenant with no rows here bills exactly what
it billed yesterday. That is the whole migration's safety story.

Revision ID: 128_what_a_school_pays_for_and_what_it_costs_us
Revises: 127_the_door_records_who_came_through_it
"""

import sqlalchemy as sa
from alembic import op

revision = "128_what_a_school_pays_for_and_what_it_costs_us"
down_revision = "127_the_door_records_who_came_through_it"
branch_labels = None
depends_on = None

PRICING_MODES = "('metered', 'fixed', 'pass_through')"


def upgrade():
    op.create_table(
        "service_providers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(60), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "provider_services",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("service_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # What one unit of quantity *is*. A usage row without this would be a
        # number nobody could price.
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column(
            "pricing_mode", sa.String(30), nullable=False, server_default="metered"
        ),
        # What the provider charges NexSchool. Internal; never returned to a
        # school by any customer-facing payload.
        sa.Column("provider_unit_cost", sa.Numeric(12, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("provider_id", "key", name="uq_provider_services_key"),
        sa.CheckConstraint(
            f"pricing_mode IN {PRICING_MODES}", name="ck_provider_services_pricing_mode"
        ),
    )
    op.create_index(
        "idx_provider_services_provider_id", "provider_services", ["provider_id"]
    )

    op.create_table(
        "tenant_services",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # RESTRICT, not CASCADE: deleting a service somebody is being charged
        # for should fail loudly rather than quietly erase their terms.
        sa.Column(
            "service_id",
            sa.String(36),
            sa.ForeignKey("provider_services.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("pricing_mode", sa.String(30), nullable=True),
        # The school's price and NexSchool's cost, side by side and separate.
        sa.Column("customer_unit_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("customer_fixed_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("provider_unit_cost", sa.Numeric(12, 4), nullable=True),
        sa.Column("estimated_annual_quantity", sa.Numeric(14, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "service_id", name="uq_tenant_services_service"),
        sa.CheckConstraint(
            f"pricing_mode IS NULL OR pricing_mode IN {PRICING_MODES}",
            name="ck_tenant_services_pricing_mode",
        ),
    )
    op.create_index("idx_tenant_services_tenant_id", "tenant_services", ["tenant_id"])
    op.create_index("idx_tenant_services_service_id", "tenant_services", ["service_id"])

    op.create_table(
        "service_usage_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_service_id",
            sa.String(36),
            sa.ForeignKey("tenant_services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        # Copied from the service at write time, so a catalog that later
        # changes its unit cannot reinterpret history.
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("usage_type", sa.String(60), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(60), nullable=True),
        # The provider's own id for the event. See the unique index below.
        sa.Column("external_reference", sa.String(120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_service_usage_tenant_service",
        "service_usage_records",
        ["tenant_id", "tenant_service_id"],
    )
    op.create_index(
        "idx_service_usage_occurred_at",
        "service_usage_records",
        ["tenant_id", "occurred_at"],
    )
    # Idempotency, enforced by the database rather than by a read-then-write:
    # a replayed provider webhook cannot turn one message into two even if two
    # workers race on it. Partial, because rows with no provider id are not
    # deduplicable and must not collide with each other.
    op.create_index(
        "uq_service_usage_external_reference",
        "service_usage_records",
        ["tenant_id", "tenant_service_id", "external_reference"],
        unique=True,
        postgresql_where=sa.text("external_reference IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_service_usage_external_reference", table_name="service_usage_records")
    op.drop_index("idx_service_usage_occurred_at", table_name="service_usage_records")
    op.drop_index("idx_service_usage_tenant_service", table_name="service_usage_records")
    op.drop_table("service_usage_records")

    op.drop_index("idx_tenant_services_service_id", table_name="tenant_services")
    op.drop_index("idx_tenant_services_tenant_id", table_name="tenant_services")
    op.drop_table("tenant_services")

    op.drop_index("idx_provider_services_provider_id", table_name="provider_services")
    op.drop_table("provider_services")

    op.drop_table("service_providers")
