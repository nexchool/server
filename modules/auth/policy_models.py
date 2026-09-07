"""Which authentication methods a school permits, and to whom.

Configuration, not behaviour. Nothing in this phase consults these tables:
login resolves and verifies exactly as it did before, and the pipeline that
will read this arrives in a later phase. What exists here is the answer to a
question the product could not previously be asked —

    which ways in does this school allow, for which of its people, on which
    application?

— stored where it can be constrained, queried per rule, and audited.

**Not in `tenants.feature_flags`, deliberately.** That column is a JSON bag
whose updater merges and never prunes, so keys outlive the modules that named
them: `RETIRED_FEATURE_KEYS` lists six still stored as `true` on live tenants,
and one of them switched a module on in production because a stored value beat
its default. Authentication policy is the last thing that should inherit a
stale answer, and a JSON bag cannot express "who enabled this, and when".

**Absence means denied.** An enabled rule permits a method; no row denies it.
This is the opposite of the feature-flag convention, where a missing key means
enabled — and it is the opposite on purpose.
"""

from __future__ import annotations

import uuid

from core.database import db
from core.models import TenantBaseModel
from core.school_time import utc_now


# --- family access (ADR-011) -----------------------------------------------

#: The default. The Student relationship carries the account; parents are
#: recorded as People and Family Members and receive no login of their own.
FAMILY_ACCESS_SHARED = "shared_with_student"
#: Parents receive their own account and a Parent context.
FAMILY_ACCESS_SEPARATE = "separate_parent_login"
FAMILY_ACCESS_MODES = (FAMILY_ACCESS_SHARED, FAMILY_ACCESS_SEPARATE)

# --- what happens to a credential the school issued -------------------------

CREDENTIAL_FORCE_CHANGE = "force_change_on_first_login"
CREDENTIAL_NO_FORCED_CHANGE = "no_forced_change"
STUDENT_CREDENTIAL_POLICIES = (CREDENTIAL_FORCE_CHANGE, CREDENTIAL_NO_FORCED_CHANGE)

# --- who a rule is about ----------------------------------------------------
#
# Derived from the person's relationships, never stored on the account, and a
# union rather than a partition: a teacher whose child studies here holds both
# `staff` and `parent`.

SUBJECT_STUDENT = "student"
SUBJECT_STAFF = "staff"
SUBJECT_PARENT = "parent"
SUBJECT_KINDS = (SUBJECT_STUDENT, SUBJECT_STAFF, SUBJECT_PARENT)

#: A rule that applies wherever the account signs in from. Every seeded rule
#: uses this: surface is recorded but narrows nothing until a school asks it
#: to. Deliberately not a closed list — a surface is a client application, and
#: new ones appear without the identity model needing to know.
SURFACE_ANY = "any"


class TenantAuthPolicy(TenantBaseModel):
    """One school's authentication settings. Exactly one row per tenant."""

    __tablename__ = "tenant_auth_policies"

    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )

    #: ADR-011's per-organization setting. Stored here from the moment the
    #: policy exists, and inert until the phase that issues parent logins.
    family_access_mode = db.Column(
        db.String(30),
        nullable=False,
        default=FAMILY_ACCESS_SHARED,
        server_default=FAMILY_ACCESS_SHARED,
    )

    #: Whether a school-issued credential must be replaced on first use.
    #: Records the intent; the enforcement it will drive is unchanged for now.
    student_credential_policy = db.Column(
        db.String(40),
        nullable=False,
        default=CREDENTIAL_FORCE_CHANGE,
        server_default=CREDENTIAL_FORCE_CHANGE,
    )

    updated_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    rules = db.relationship(
        "TenantAuthPolicyRule",
        primaryjoin="TenantAuthPolicy.tenant_id == foreign(TenantAuthPolicyRule.tenant_id)",
        viewonly=True,
        lazy=True,
    )

    __table_args__ = (
        db.CheckConstraint(
            "family_access_mode IN ('shared_with_student', 'separate_parent_login')",
            name="ck_tenant_auth_policies_family_access_mode",
        ),
        db.CheckConstraint(
            "student_credential_policy IN "
            "('force_change_on_first_login', 'no_forced_change')",
            name="ck_tenant_auth_policies_student_credential_policy",
        ),
    )

    def __repr__(self):
        return f"<TenantAuthPolicy tenant={self.tenant_id}>"


class TenantAuthPolicyRule(TenantBaseModel):
    """One permission: this kind of person, on this surface, may use this method.

    A disabled rule is kept rather than deleted. Deleting it would lose the
    fact that somebody decided against the method, and who — which is most of
    what makes this table worth having over a JSON bag.
    """

    __tablename__ = "tenant_auth_policy_rules"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    subject_kind = db.Column(db.String(20), nullable=False)
    #: `any`, or a named client application. Free text on purpose: a surface is
    #: whatever application exists, and the schema should not need a migration
    #: to learn about a new one.
    surface = db.Column(
        db.String(30), nullable=False, default=SURFACE_ANY, server_default=SURFACE_ANY
    )
    #: A key from the authentication strategy registry that a later phase adds
    #: — `email_password`, `admission_id_password`, `mobile_otp`, `mobile_pin`.
    #: Wide enough for keys longer than the ones declared today.
    method_key = db.Column(db.String(40), nullable=False)

    is_enabled = db.Column(
        db.Boolean, nullable=False, default=True, server_default=db.text("true")
    )
    enabled_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    enabled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    #: Room for the reason a school was given a method — the risk
    #: acknowledgement a weaker method should carry, for instance.
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    __table_args__ = (
        db.CheckConstraint(
            "subject_kind IN ('student', 'staff', 'parent')",
            name="ck_tenant_auth_policy_rules_subject_kind",
        ),
        # One answer per question. Two rows saying different things about the
        # same (school, kind, surface, method) would make the policy
        # unreadable, so the database refuses them.
        db.UniqueConstraint(
            "tenant_id",
            "subject_kind",
            "surface",
            "method_key",
            name="uq_tenant_auth_policy_rules",
        ),
        db.Index(
            "idx_tenant_auth_policy_rules_lookup",
            "tenant_id",
            "subject_kind",
        ),
    )

    def __repr__(self):
        return (
            f"<TenantAuthPolicyRule {self.subject_kind}/{self.surface}/"
            f"{self.method_key} enabled={self.is_enabled}>"
        )
