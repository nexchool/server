"""Hostel gatepasses and audit trail tables.

- hostel_gatepasses: student night/day-out requests with state machine.
- hostel_gatepass_audit: append-only log of every gatepass state change.

Gatepass workflow:
  pending -> approved -> active -> closed (happy path)
  pending -> rejected (warden denial)
  active -> overdue (system, return time passed + grace period)

Parent contact is recorded; security guard calls parent before approval.
Parent notification is informational only (in-app + push), not action-required.

Revision ID: 058_hostel_gatepasses
Revises: 057_hostel_visitors
Create Date: 2026-05-11

"""

from alembic import op
import sqlalchemy as sa


revision = "058_hostel_gatepasses"
down_revision = "057_hostel_visitors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # hostel_gatepasses
    op.create_table(
        "hostel_gatepasses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.String(36),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "hostel_id",
            sa.String(36),
            sa.ForeignKey("hostels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(20), nullable=False),  # day_out, night_out
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),  # pending, approved, active, closed, rejected, overdue
        sa.Column(
            "requested_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("actual_out_at", sa.DateTime(), nullable=True),
        sa.Column("actual_in_at", sa.DateTime(), nullable=True),
        sa.Column("departure_datetime", sa.DateTime(), nullable=False),
        sa.Column("expected_return_datetime", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("parent_phone", sa.String(20), nullable=False),
        sa.Column(
            "parent_consent_status",
            sa.String(20),
            nullable=False,
            server_default="not_required",
        ),  # not_required, pending, given, rejected
        sa.Column("parent_consent_notified_at", sa.DateTime(), nullable=True),
        sa.Column(
            "parent_notification_type",
            sa.String(50),
            nullable=True,
        ),  # comma-separated: in_app, push, sms
        sa.Column("approved_by_user_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_hostel_gatepasses_tenant_id", "hostel_gatepasses", ["tenant_id"]
    )
    op.create_index(
        "ix_hostel_gatepasses_student_id", "hostel_gatepasses", ["student_id"]
    )
    op.create_index(
        "ix_hostel_gatepasses_hostel_id", "hostel_gatepasses", ["hostel_id"]
    )
    # For overdue detection: WHERE status='active' AND expected_return_datetime < now()
    op.create_index(
        "ix_hostel_gatepasses_status_return",
        "hostel_gatepasses",
        ["status", "expected_return_datetime"],
    )

    # hostel_gatepass_audit (append-only)
    op.create_table(
        "hostel_gatepass_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "gatepass_id",
            sa.String(36),
            sa.ForeignKey("hostel_gatepasses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.String(50),
            nullable=False,
        ),  # created, approved, rejected, checkout, checkin, marked_overdue
        sa.Column(
            "actor_type",
            sa.String(20),
            nullable=False,
        ),  # student, warden, gatekeeper, system
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_hostel_gatepass_audit_gatepass_id",
        "hostel_gatepass_audit",
        ["gatepass_id"],
    )
    op.create_index(
        "ix_hostel_gatepass_audit_created_at",
        "hostel_gatepass_audit",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hostel_gatepass_audit_created_at",
        table_name="hostel_gatepass_audit",
    )
    op.drop_index(
        "ix_hostel_gatepass_audit_gatepass_id",
        table_name="hostel_gatepass_audit",
    )
    op.drop_table("hostel_gatepass_audit")
    op.drop_index(
        "ix_hostel_gatepasses_status_return",
        table_name="hostel_gatepasses",
    )
    op.drop_index(
        "ix_hostel_gatepasses_hostel_id", table_name="hostel_gatepasses"
    )
    op.drop_index(
        "ix_hostel_gatepasses_student_id", table_name="hostel_gatepasses"
    )
    op.drop_index(
        "ix_hostel_gatepasses_tenant_id", table_name="hostel_gatepasses"
    )
    op.drop_table("hostel_gatepasses")
