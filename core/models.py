"""
Core Models

Tenant, Plan, AuditLog, and TenantBaseModel for multi-tenant SaaS.
All tenant-scoped business models inherit from TenantBaseModel.
"""

from datetime import datetime
import uuid

from core.database import db


# Status values for Tenant
TENANT_STATUS_TRIAL = "trial"      # Pre-paid trial; writes allowed until trial_ends_at.
TENANT_STATUS_ACTIVE = "active"
TENANT_STATUS_SUSPENDED = "suspended"
TENANT_STATUS_DELETED = "deleted"  # Soft delete; login and API access blocked
TENANT_STATUSES = (
    TENANT_STATUS_TRIAL,
    TENANT_STATUS_ACTIVE,
    TENANT_STATUS_SUSPENDED,
    TENANT_STATUS_DELETED,
)

# Billing cycles. We only model 'yearly' today; the column exists so we
# can add 'monthly' / 'termly' without another migration when we need it.
BILLING_CYCLE_YEARLY = "yearly"
BILLING_CYCLES = (BILLING_CYCLE_YEARLY,)

# Default keys for platform settings (stored in platform_settings table)
PLATFORM_SETTING_KEYS = [
    "platform_name",
    "maintenance_mode",
    "session_timeout_minutes",
    "max_login_attempts",
    "email_from_name",
    "support_email",
]


class Plan(db.Model):
    """
    Plan Model (platform-level, not tenant-scoped).

    Subscription plan defining limits (max_students, max_teachers) and price.
    """
    __tablename__ = "plans"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    price_monthly = db.Column(db.Numeric(12, 2), nullable=False)
    max_students = db.Column(db.Integer, nullable=False)
    max_teachers = db.Column(db.Integer, nullable=False)
    features_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def __repr__(self):
        return f"<Plan {self.name}>"


class Tenant(db.Model):
    """
    Tenant Model

    Represents a school/organization in the multi-tenant SaaS.
    All business data is scoped by tenant_id.
    """
    __tablename__ = "tenants"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(255), nullable=False)
    subdomain = db.Column(db.String(63), unique=True, nullable=False, index=True)
    contact_email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.Text, nullable=True)
    plan_id = db.Column(
        db.String(36),
        db.ForeignKey("plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    logo_url = db.Column(db.String(500), nullable=True)
    tagline = db.Column(db.String(255), nullable=True)
    board_affiliation = db.Column(db.String(100), nullable=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default=TENANT_STATUS_ACTIVE,
        index=True
    )  # active | suspended

    # Per-tenant subscription model (replaces shared Plan).
    price_per_student_per_year = db.Column(db.Numeric(12, 2), nullable=True)
    discount_percentage = db.Column(db.Numeric(5, 2), nullable=True)
    discount_start_date = db.Column(db.Date, nullable=True)
    discount_end_date = db.Column(db.Date, nullable=True)
    feature_flags = db.Column(db.JSON, nullable=False, default=dict)

    # Subscription state (Phase 5).
    # The pricing columns above already capture price/discount; the new
    # columns track lifecycle. `status` carries trial/active/suspended/
    # deleted (see TENANT_STATUSES); a dedicated TenantSubscription table
    # would duplicate the pricing columns we already have.
    trial_ends_at = db.Column(db.DateTime, nullable=True)
    billing_cycle = db.Column(
        db.String(20),
        nullable=False,
        default=BILLING_CYCLE_YEARLY,
        server_default=BILLING_CYCLE_YEARLY,
    )

    # School-setup wizard completion gate. False until POST /school-setup/complete.
    is_setup_complete = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.text("false"),
    )
    setup_completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    setup_completed_by = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    setup_reconfirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Offboarding lifecycle
    offboarding_started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    purge_scheduled_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Setup metadata
    setup_template_used = db.Column(
        db.String(50),
        nullable=True,
        comment="board_code of template used at setup: cbse, icse, gujarat_state_board, ib, custom",
    )

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    plan = db.relationship("Plan", backref="tenants", lazy=True)

    def __repr__(self):
        return f"<Tenant {self.subdomain}>"


class AuditLog(db.Model):
    """
    Audit log for platform-critical actions (tenant created, suspended, plan changed, etc.).
    Not tenant-scoped; tenant_id nullable for platform-wide actions.
    """
    __tablename__ = "audit_logs"
    __tenant_scoped__ = False

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    platform_admin_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action = db.Column(db.String(100), nullable=False, index=True)
    # Python name 'extra_data' to avoid conflict with SQLAlchemy's reserved 'metadata'
    extra_data = db.Column("metadata", db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<AuditLog {self.action} {self.created_at}>"


class TenantUsage(db.Model):
    """
    TenantUsage

    One row per tenant. Tracks the metrics that drive billing — currently
    just `active_students_count`, snapshotted whenever the student
    lifecycle changes. Read by the billing service and surfaced to the
    super-admin panel.

    Not a TenantBaseModel because the row is platform-managed: it is
    written by service hooks rather than by tenant-scoped business logic,
    and queries always go through `tenant_id` explicitly.
    """

    __tablename__ = "tenant_usage"
    __tenant_scoped__ = False

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    active_students_count = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    last_updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def __repr__(self):
        return f"<TenantUsage tenant={self.tenant_id} students={self.active_students_count}>"


class PlatformSetting(db.Model):
    """
    Key-value store for platform (super admin) settings.
    Not tenant-scoped.
    """
    __tablename__ = "platform_settings"
    __tenant_scoped__ = False

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TenantBaseModel(db.Model):
    """
    Abstract base model for all tenant-scoped business entities.

    - Adds tenant_id (FK to tenants.id, NOT NULL, indexed).
    - Subclasses are automatically filtered by tenant in queries when
      tenant resolution middleware has set g.tenant_id.

    All business models (users, sessions, roles, user_roles, role_permissions,
    students, teachers, classes, class_teachers, attendance) must inherit
    from this to prevent cross-tenant data leakage.
    """
    __abstract__ = True
    __tenant_scoped__ = True  # Used by query filter to apply tenant scope

    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
