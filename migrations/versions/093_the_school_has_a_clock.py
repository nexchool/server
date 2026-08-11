"""The school has a clock of its own

Two questions were being answered by the server's own clock, and both were the
wrong question to ask it.

"When did this happen" was stored naive. The value was UTC, but nothing said so,
so `.isoformat()` emitted `2026-08-02T23:02:13` with no offset — and JavaScript
reads an offsetless datetime as *local*. An announcement written at 04:32 IST
was displayed to every user as 23:02 the previous evening. Not a rounding error:
the wrong time on the wrong day, on every naive column that reaches a screen.

"What day is it at the school" was `date.today()`, which is the server's date.
Ours runs UTC, so from midnight to 05:30 IST it is still on yesterday — the
window that hostel gate passes and the morning bus run fall into.

This fixes the storage half. Every naive timestamp column becomes
`timestamptz`, its existing values read as UTC because that is what wrote them,
and tenants gain the zone their clocks actually run on. The call sites that ask
what day it is move to `core.school_time` in the same change.

The column list is spelled out rather than discovered at run time so that the
diff shows exactly what changes, and so the downgrade reverts exactly these and
not the ninety-one columns that already carried an offset.

Revision ID: 093_the_school_has_a_clock
Revises: 092_teaching_has_one_owner
"""
from alembic import op
import sqlalchemy as sa


revision = "093_the_school_has_a_clock"
down_revision = "092_teaching_has_one_owner"
branch_labels = None
depends_on = None


# Generated from the schema at revision 092. Every one of these held a UTC
# instant with nothing recording that it was UTC.
NAIVE_TIMESTAMP_COLUMNS: dict[str, tuple[str, ...]] = {
    "academic_programmes": ("created_at", "deleted_at", "updated_at",),
    "academic_years": ("created_at", "updated_at",),
    "attendance": ("created_at", "updated_at",),
    "audit_logs": ("created_at",),
    "classes": ("created_at", "updated_at",),
    "device_tokens": ("created_at", "last_used_at", "updated_at",),
    "fee_components": ("created_at", "updated_at",),
    "fee_invoices": ("created_at", "updated_at",),
    "fee_payments": ("created_at",),
    "fee_receipts": ("generated_at",),
    "fee_structure_classes": ("created_at",),
    "fee_structures": ("created_at", "updated_at",),
    "grades": ("created_at", "deleted_at", "updated_at",),
    "holidays": ("created_at", "updated_at",),
    "hostel_allocations": ("check_in_at", "check_out_at", "created_at", "deleted_at", "updated_at",),
    "hostel_beds": ("created_at", "deleted_at", "updated_at",),
    "hostel_gatepass_audit": ("created_at",),
    "hostel_gatepasses": ("actual_in_at", "actual_out_at", "approved_at", "created_at", "deleted_at", "departure_datetime", "expected_return_datetime", "parent_consent_notified_at", "requested_at", "updated_at",),
    "hostel_rooms": ("created_at", "deleted_at", "updated_at",),
    "hostel_visitor_logs": ("check_in_at", "check_out_at", "created_at", "deleted_at",),
    "hostel_visitors": ("created_at", "updated_at",),
    "hostels": ("created_at", "deleted_at", "updated_at",),
    "leave_policies": ("created_at", "updated_at",),
    "notification_recipients": ("created_at", "read_at",),
    "notification_templates": ("created_at", "updated_at",),
    "notifications": ("created_at", "read_at",),
    "payments": ("created_at", "updated_at",),
    "permissions": ("created_at",),
    "plans": ("created_at", "updated_at",),
    "platform_settings": ("updated_at",),
    "religions": ("created_at", "deleted_at", "updated_at",),
    "role_permissions": ("created_at",),
    "roles": ("created_at",),
    "schedule_overrides": ("created_at", "updated_at",),
    "school_units": ("created_at", "deleted_at", "updated_at",),
    "sessions": ("created_at", "last_accessed_at", "refresh_token_expires_at", "revoked_at",),
    "student_documents": ("created_at", "updated_at",),
    "student_fee_items": ("created_at", "updated_at",),
    "student_fees": ("created_at", "updated_at",),
    "student_promotion_batches": ("created_at",),
    "students": ("created_at", "updated_at",),
    "subject_load": ("created_at", "updated_at",),
    "subjects": ("created_at", "updated_at",),
    "teacher_availability": ("created_at",),
    "teacher_leave_balances": ("created_at", "last_adjusted_at", "updated_at",),
    "teacher_leaves": ("created_at", "updated_at",),
    "teacher_subjects": ("created_at",),
    "teacher_workload_rules": ("created_at", "updated_at",),
    "teachers": ("created_at", "updated_at",),
    "tenant_usage": ("last_updated_at",),
    "tenants": ("created_at", "trial_ends_at", "updated_at",),
    "timetable_config": ("created_at", "updated_at",),
    "timetable_slots": ("created_at", "updated_at",),
    "transport_bus_assignments": ("created_at", "updated_at",),
    "transport_buses": ("created_at", "updated_at",),
    "transport_drivers": ("created_at",),
    "transport_enrollments": ("created_at", "updated_at",),
    "transport_fee_plans": ("created_at",),
    "transport_route_schedules": ("created_at", "updated_at",),
    "transport_route_stops": ("created_at",),
    "transport_routes": ("created_at", "updated_at",),
    "transport_schedule_exceptions": ("created_at",),
    "transport_staff": ("created_at", "updated_at",),
    "transport_stops": ("created_at", "updated_at",),
    "users": ("created_at", "last_login_at", "login_locked_until", "reset_password_sent_at", "updated_at",),
}


def _convert(to_aware: bool) -> None:
    """Retype the columns, reading and writing the values as UTC.

    `AT TIME ZONE 'UTC'` is doing real work in both directions: going up it
    attaches the offset the value always implied, and coming down it strips it
    back to the same wall-clock reading. Without the USING clause Postgres
    would interpret the values in the *session's* timezone, which is how a
    conversion like this silently shifts a whole database by a few hours.
    """
    connection = op.get_bind()
    target = "TIMESTAMPTZ" if to_aware else "TIMESTAMP"

    for table, columns in NAIVE_TIMESTAMP_COLUMNS.items():
        for column in columns:
            connection.execute(
                sa.text(
                    f'ALTER TABLE "{table}" '
                    f'ALTER COLUMN "{column}" TYPE {target} '
                    f"USING \"{column}\" AT TIME ZONE 'UTC'"
                )
            )


def upgrade():
    op.add_column(
        "tenants",
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Asia/Kolkata",
        ),
    )
    _convert(to_aware=True)


def downgrade():
    _convert(to_aware=False)
    op.drop_column("tenants", "timezone")
