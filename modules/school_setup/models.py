"""School setup support models: per-module events and data purge audit."""

from datetime import datetime, timezone
import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

from core.database import db


class SetupModuleEvent(db.Model):
    """Records when a setup module is completed or regresses."""

    __tablename__ = "setup_module_events"
    __tenant_scoped__ = True

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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


class DataPurgeLog(db.Model):
    """Counts-only audit trail for data retention deletion jobs."""

    __tablename__ = "data_purge_logs"
    __tenant_scoped__ = True

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    data_type = db.Column(db.String(50), nullable=False)
    records_deleted = db.Column(db.Integer, nullable=False)
    purged_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class TenantOnboardingDraft(db.Model):
    """In-progress onboarding config for one tenant, autosaved by the panel form.

    Deliberately not a TenantBaseModel: platform routes run without g.tenant_id,
    so the tenant-scoping listener must not touch these queries. Same reasoning
    as SetupModuleEvent above.

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
        onupdate=datetime.utcnow,
    )
