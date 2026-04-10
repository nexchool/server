"""Route–stop junction; backfill from route-scoped stops; merge duplicate stop names.

Revision ID: 029_transport_route_stops
Revises: 028_transport_stops_global
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "029_transport_route_stops"
down_revision = "028_transport_stops_global"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transport_route_stops",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "route_id",
            sa.String(36),
            sa.ForeignKey("transport_routes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stop_id",
            sa.String(36),
            sa.ForeignKey("transport_stops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_order", sa.Integer(), nullable=False),
        sa.Column("pickup_time", sa.Time(), nullable=True),
        sa.Column("drop_time", sa.Time(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_transport_route_stops_tenant_route",
        "transport_route_stops",
        ["tenant_id", "route_id"],
    )
    op.create_index(
        "ix_transport_route_stops_tenant_stop",
        "transport_route_stops",
        ["tenant_id", "stop_id"],
    )
    op.create_unique_constraint(
        "uq_transport_route_stops_tenant_route_seq",
        "transport_route_stops",
        ["tenant_id", "route_id", "sequence_order"],
    )
    op.create_unique_constraint(
        "uq_transport_route_stops_tenant_route_stop",
        "transport_route_stops",
        ["tenant_id", "route_id", "stop_id"],
    )

    op.execute(
        text(
            """
            INSERT INTO transport_route_stops (
                id, tenant_id, route_id, stop_id, sequence_order, pickup_time, drop_time, created_at
            )
            SELECT
                gen_random_uuid()::text,
                tenant_id,
                route_id,
                id,
                sequence_order,
                pickup_time,
                drop_time,
                now()
            FROM transport_stops
            WHERE route_id IS NOT NULL
            """
        )
    )

    op.execute(text("UPDATE transport_stops SET route_id = NULL WHERE route_id IS NOT NULL"))

    bind = op.get_bind()
    dup_groups = bind.execute(
        text(
            """
            SELECT tenant_id, lower(name) AS lname, array_agg(id ORDER BY id) AS ids
            FROM transport_stops
            GROUP BY tenant_id, lower(name)
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()

    for row in dup_groups:
        ids = list(row.ids)
        keep_id = ids[0]
        for dup_id in ids[1:]:
            jrows = bind.execute(
                text("SELECT id, route_id FROM transport_route_stops WHERE stop_id = :d"),
                {"d": dup_id},
            ).fetchall()
            for j in jrows:
                conflict = bind.execute(
                    text(
                        """
                        SELECT id FROM transport_route_stops
                        WHERE route_id = :r AND stop_id = :k AND id != :jid
                        """
                    ),
                    {"r": j.route_id, "k": keep_id, "jid": j.id},
                ).scalar()
                if conflict:
                    bind.execute(
                        text("DELETE FROM transport_route_stops WHERE id = :jid"),
                        {"jid": j.id},
                    )
                else:
                    bind.execute(
                        text(
                            "UPDATE transport_route_stops SET stop_id = :k WHERE id = :jid"
                        ),
                        {"k": keep_id, "jid": j.id},
                    )
            bind.execute(
                text(
                    "UPDATE transport_enrollments SET pickup_stop_id = :k WHERE pickup_stop_id = :d"
                ),
                {"k": keep_id, "d": dup_id},
            )
            bind.execute(
                text("UPDATE transport_enrollments SET drop_stop_id = :k WHERE drop_stop_id = :d"),
                {"k": keep_id, "d": dup_id},
            )
            bind.execute(text("DELETE FROM transport_stops WHERE id = :d"), {"d": dup_id})

    op.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_transport_stops_tenant_lower_name
            ON transport_stops (tenant_id, (lower(name)))
            """
        )
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS uq_transport_stops_tenant_lower_name"))
    op.drop_constraint("uq_transport_route_stops_tenant_route_stop", "transport_route_stops", type_="unique")
    op.drop_constraint("uq_transport_route_stops_tenant_route_seq", "transport_route_stops", type_="unique")
    op.drop_index("ix_transport_route_stops_tenant_stop", table_name="transport_route_stops")
    op.drop_index("ix_transport_route_stops_tenant_route", table_name="transport_route_stops")
    op.drop_table("transport_route_stops")
