"""Which provider carries a school's work, for each capability.

One table. It answers a routing question — *when this school sends an SMS,
whose wire does it go down* — and nothing else.

**Why this is not `tenant_services`.** Phase 2's table answers a commercial
question: this school buys this service, at these prices. The two look similar
and are not. A school can be commercially signed up to two SMS vendors while
only one carries live traffic; prices outlive routing changes; and putting an
endpoint or a credential reference on a billing row would make a billing model
responsible for how an HTTP call is made. They share a vendor identity —
`provider_key` matches `service_providers.key` — so an operator reading a bill
and an operator reading a log see the same name, and nothing else.

Tenant-scoped, because provider selection is per school: two schools may use
different vendors for the same capability, and resolving an integration
without a school would be a wrong answer rather than merely a leak.
"""

from __future__ import annotations

import uuid

from core.database import db
from core.models import TenantBaseModel
from core.school_time import utc_now

from .capabilities import CAPABILITIES, STATUS_DISABLED, STATUSES


class TenantIntegration(TenantBaseModel):
    """This school's provider for one capability."""

    __tablename__ = "tenant_integrations"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    #: What this integration does — `sms`. Not a vendor name.
    capability = db.Column(db.String(40), nullable=False)
    #: Which vendor. Matches `service_providers.key` and a registered client.
    provider_key = db.Column(db.String(60), nullable=False)

    #: Disabled by default. A row appearing must not start carrying traffic;
    #: somebody enables it deliberately, after checking it.
    status = db.Column(
        db.String(20), nullable=False, default=STATUS_DISABLED, server_default=STATUS_DISABLED
    )

    #: Non-secret settings — a sender id, a route, a base URL. Safe to return
    #: from an API and safe in a log, which is only true because the next
    #: column is where secrets are *referred to* rather than kept.
    configuration = db.Column(db.JSON, nullable=False, default=dict, server_default="{}")

    #: Purpose → environment variable name. **Names, never values.** Reading
    #: this row tells you which credential is in use and nothing about what it
    #: is; see `credentials.py` for why the value is not here.
    credential_references = db.Column(
        db.JSON, nullable=False, default=dict, server_default="{}"
    )

    #: Why it is in the state it is in — the last configuration failure, in
    #: words an operator can act on. Never a provider's raw response.
    status_detail = db.Column(db.Text, nullable=True)
    last_checked_at = db.Column(db.DateTime(timezone=True), nullable=True)

    enabled_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    enabled_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        # One provider per capability per school. Selection has to be
        # unambiguous, and a unique index is a better guarantee of that than a
        # query that remembers to order deterministically.
        db.UniqueConstraint(
            "tenant_id", "capability", name="uq_tenant_integrations_capability"
        ),
        db.Index("idx_tenant_integrations_tenant_id", "tenant_id"),
        db.CheckConstraint(
            "capability IN " + str(tuple(CAPABILITIES)).replace(",)", ")"),
            name="ck_tenant_integrations_capability",
        ),
        db.CheckConstraint(
            "status IN " + str(tuple(STATUSES)),
            name="ck_tenant_integrations_status",
        ),
    )

    def to_dict(self):
        """What an operator may see.

        Carries the credential *names* and whether each is set, never a value —
        there is no field here that could hold one.
        """
        from .credentials import describe_references

        return {
            "id": self.id,
            "capability": self.capability,
            "provider_key": self.provider_key,
            "status": self.status,
            "configuration": self.configuration or {},
            "credentials": describe_references(self.credential_references or {}),
            "status_detail": self.status_detail,
            "last_checked_at": (
                self.last_checked_at.isoformat() if self.last_checked_at else None
            ),
            "enabled_at": self.enabled_at.isoformat() if self.enabled_at else None,
        }

    def __repr__(self):
        return f"<TenantIntegration {self.capability} via {self.provider_key}>"
