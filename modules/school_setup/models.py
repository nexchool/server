"""School setup support models: per-module events and data purge audit."""

from datetime import datetime, timezone
import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

from core.database import db
from core.models import TenantBaseModel
from core.school_time import utc_now


class SetupModuleEvent(TenantBaseModel):
    """Records when a setup module is completed or regresses.

    A TenantBaseModel so the tenant scope actually applies; it previously
    declared ``__tenant_scoped__ = True``, a flag nothing reads. The scoping
    listener is inert outside a request and when no tenant is resolved, so
    the platform and Celery paths that touch this table are unaffected.
    """

    __tablename__ = "setup_module_events"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    module = db.Column(db.String(50), nullable=False)
    event = db.Column(db.String(50), nullable=False)  # 'completed', 'regressed', 'setup_complete', 'setup_reconfirmed'
    actor_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    def __repr__(self):
        return f"<SetupModuleEvent {self.module}:{self.event} tenant={self.tenant_id}>"


class DataPurgeLog(TenantBaseModel):
    """Counts-only audit trail for data retention deletion jobs.

    A TenantBaseModel for the same reason as SetupModuleEvent above. The
    retention jobs that write it run without a request context, where the
    scoping listener does nothing, so they keep working across all tenants.
    """

    __tablename__ = "data_purge_logs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    data_type = db.Column(db.String(50), nullable=False)
    records_deleted = db.Column(db.Integer, nullable=False)
    purged_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class TenantOnboardingDraft(db.Model):
    """In-progress onboarding config for one tenant, autosaved by the panel form.

    Not a TenantBaseModel because this row belongs to the platform operator
    onboarding a school, not to the school — it exists before the tenant is
    usable, and only `/api/platform/*` reads it. (An earlier note here claimed
    the scoping listener had to be kept away from these queries; that is not
    the reason — the listener is already inert when no tenant is resolved,
    which is the case on every platform route.)

    Server-side rather than browser storage so that a draft survives a switched
    machine, and so an operator's actual input is inspectable when they report a
    problem.
    """

    __tablename__ = "tenant_onboarding_drafts"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    config = db.Column(JSONB, nullable=False)
    updated_by = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=utc_now,
    )
