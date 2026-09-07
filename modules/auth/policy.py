"""Answering "which ways in does this school allow this person?"

Evaluation only. Nothing here authenticates, resolves an identifier or
verifies a credential — it reads configuration and returns method keys. The
pipeline that consumes it arrives in a later phase; this module exists now so
that phase inherits a decided answer rather than inventing one.

Three rules carry the design, and each is a test:

**Subject kind is a union, not a partition.** A person is whatever their
relationships make them. A teacher whose child studies here is `staff` *and*
`parent`, and is offered whatever either kind may use. Any design in which she
must pick an identity at the login screen re-creates the several-accounts
problem ADR-004 exists to prevent.

**Absence means denied.** An enabled rule permits; no row refuses. The
opposite of `core/feature_flags.py`, deliberately — see `policy_models.py`.

**Platform admins are exempt (A3).** A school that selects one method must not
be able to lock the operator out of its own tenancy, so policy is not
evaluated for them at all.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Set

from core.database import db

from .policy_models import (
    CREDENTIAL_FORCE_CHANGE,
    FAMILY_ACCESS_MODES,
    FAMILY_ACCESS_SEPARATE,
    FAMILY_ACCESS_SHARED,
    SUBJECT_KINDS,
    SUBJECT_PARENT,
    SUBJECT_STAFF,
    STUDENT_CREDENTIAL_POLICIES,
    SUBJECT_STUDENT,
    SURFACE_ANY,
    TenantAuthPolicy,
    TenantAuthPolicyRule,
)

#: What a school gets when nothing has been configured for it, and what every
#: existing school was seeded with: today's behaviour, exactly.
DEFAULT_METHOD_KEY = "email_password"
DEFAULT_ENABLED_RULES = tuple(
    (subject_kind, SURFACE_ANY, DEFAULT_METHOD_KEY) for subject_kind in SUBJECT_KINDS
)


def policy_for(tenant_id: str) -> Optional[TenantAuthPolicy]:
    """This school's policy row, or None if it has none yet."""
    return db.session.get(TenantAuthPolicy, tenant_id)


def family_access_mode(tenant_id: str) -> str:
    """ADR-011's setting. Defaults to shared access for a school with no row,
    because that is what a school with no configuration does today."""
    policy = policy_for(tenant_id)
    return policy.family_access_mode if policy else FAMILY_ACCESS_SHARED


def student_credential_policy(tenant_id: str) -> str:
    policy = policy_for(tenant_id)
    return policy.student_credential_policy if policy else CREDENTIAL_FORCE_CHANGE


def subject_kinds(account) -> Set[str]:
    """What this account's person is to the school, as a set.

    Asked of People and the employment record rather than recomputed here: the
    question "what is this person to us" already has an owner, and a second
    implementation of it would drift from the first.
    """
    if account is None:
        return set()

    person = getattr(account, "person", None)
    if person is None:
        return set()

    from modules.people.relationships import PersonRelationship, relationships_held_by

    held = relationships_held_by(person)
    kinds: Set[str] = set()

    # Employment, whether or not it carries teaching — a teacher is staff.
    if PersonRelationship.EMPLOYMENT in held or PersonRelationship.TEACHING in held:
        kinds.add(SUBJECT_STAFF)

    if PersonRelationship.STUDENTSHIP in held:
        kinds.add(SUBJECT_STUDENT)

    # Parent is a kind only where the school issues parent logins. Under
    # shared access there is no parent experience to permit a method for
    # (ADR-011), so being somebody's mother is a relationship, not a subject.
    if PersonRelationship.FAMILY_MEMBERSHIP in held and _is_a_parent_kind(person):
        if family_access_mode(account.tenant_id) == FAMILY_ACCESS_SEPARATE:
            kinds.add(SUBJECT_PARENT)

    return kinds


def _is_a_parent_kind(person) -> bool:
    """True if this person is a responsible adult in a household, not a child.

    The child's own membership is what makes them a student's sibling, not a
    student's parent, so it is excluded.
    """
    from modules.people.models import FAMILY_ROLE_CHILD

    return any(
        membership.relationship != FAMILY_ROLE_CHILD
        for membership in (getattr(person, "family_memberships", None) or [])
    )


def allowed_methods(account, surface: str = SURFACE_ANY) -> List[str]:
    """The authentication methods this account may use on this surface.

    Sorted and de-duplicated. Empty is a denial, not an oversight.

    **Two absences, and they mean different things.** A school with a policy
    row has been asked the question, so a method with no enabled rule is
    refused — that is the anti-feature-flag rule, and it is what
    `is_method_allowed` enforces. A school with *no policy row at all* has
    never been asked, and treating that as "refuse everything" would brick any
    tenant created by a path that does not seed one: a seed script, a fixture,
    a future onboarding route. Being unconfigured therefore means the
    product's default behaviour, which is exactly what `ensure_default_policy`
    would have written.

    The policy row is what marks a school as configured. That distinction is
    the whole of the difference, and it is why the row exists separately from
    its rules.
    """
    if account is None:
        return []

    # A3. The operator's way into a tenant is not the tenant's to withdraw.
    if getattr(account, "is_platform_admin", False):
        return sorted(methods_declared_for(account.tenant_id)) or [DEFAULT_METHOD_KEY]

    kinds = subject_kinds(account)

    if policy_for(account.tenant_id) is None:
        return [DEFAULT_METHOD_KEY]

    if not kinds:
        return []

    return methods_for(account.tenant_id, kinds, surface)


def methods_for(
    tenant_id: str, kinds: Iterable[str], surface: str = SURFACE_ANY
) -> List[str]:
    """The enabled methods for these subject kinds on this surface.

    A rule matches when its surface is the one asked about or `any`. Asking
    about `any` matches only `any` rules — a caller that does not know its
    surface is not thereby entitled to a surface-specific permission.
    """
    kinds = list(kinds)
    if not kinds:
        return []

    surfaces = {SURFACE_ANY} if surface == SURFACE_ANY else {surface, SURFACE_ANY}

    rows = (
        db.session.query(TenantAuthPolicyRule.method_key)
        .filter(
            TenantAuthPolicyRule.tenant_id == tenant_id,
            TenantAuthPolicyRule.subject_kind.in_(kinds),
            TenantAuthPolicyRule.surface.in_(surfaces),
            TenantAuthPolicyRule.is_enabled.is_(True),
        )
        .all()
    )
    return sorted({row[0] for row in rows})


def methods_declared_for(tenant_id: str) -> Set[str]:
    """Every enabled method in this school, whoever it is for. Used only for
    the platform-admin answer, which is not narrowed by subject kind."""
    rows = (
        db.session.query(TenantAuthPolicyRule.method_key)
        .filter(
            TenantAuthPolicyRule.tenant_id == tenant_id,
            TenantAuthPolicyRule.is_enabled.is_(True),
        )
        .all()
    )
    return {row[0] for row in rows}


def is_method_allowed(account, method_key: str, surface: str = SURFACE_ANY) -> bool:
    """Absence means denied."""
    return method_key in allowed_methods(account, surface)


def ensure_default_policy(tenant_id: str, *, updated_by_user_id: str = None) -> TenantAuthPolicy:
    """Give this school the default policy if it has none.

    Idempotent, and the defaults are deliberately equivalent to the product's
    behaviour before any of this existed — so creating a policy can never take
    away a way in that somebody was already using.

    Does not commit: the caller owns the transaction, so a tenant that fails to
    be created leaves no policy behind.
    """
    policy = policy_for(tenant_id)
    if policy is None:
        policy = TenantAuthPolicy(
            tenant_id=tenant_id,
            family_access_mode=FAMILY_ACCESS_SHARED,
            student_credential_policy=CREDENTIAL_FORCE_CHANGE,
            updated_by_user_id=updated_by_user_id,
        )
        db.session.add(policy)

    existing = {
        (rule.subject_kind, rule.surface, rule.method_key)
        for rule in db.session.query(TenantAuthPolicyRule).filter(
            TenantAuthPolicyRule.tenant_id == tenant_id
        )
    }
    for subject_kind, surface, method_key in DEFAULT_ENABLED_RULES:
        if (subject_kind, surface, method_key) in existing:
            continue
        db.session.add(
            TenantAuthPolicyRule(
                tenant_id=tenant_id,
                subject_kind=subject_kind,
                surface=surface,
                method_key=method_key,
                is_enabled=True,
                enabled_by_user_id=updated_by_user_id,
                enabled_at=db.func.now(),
                notes="Seeded default: the school's behaviour before "
                "authentication policy existed.",
            )
        )

    db.session.flush()
    return policy


def describe(tenant_id: str) -> dict:
    """The policy as the platform panel reads it. Configuration only — no
    account, no identifier, no credential, nothing secret."""
    policy = policy_for(tenant_id)
    rules = (
        db.session.query(TenantAuthPolicyRule)
        .filter(TenantAuthPolicyRule.tenant_id == tenant_id)
        .order_by(
            TenantAuthPolicyRule.subject_kind,
            TenantAuthPolicyRule.surface,
            TenantAuthPolicyRule.method_key,
        )
        .all()
    )

    return {
        "tenant_id": tenant_id,
        "family_access_mode": (
            policy.family_access_mode if policy else FAMILY_ACCESS_SHARED
        ),
        "student_credential_policy": (
            policy.student_credential_policy if policy else CREDENTIAL_FORCE_CHANGE
        ),
        # True when the school has no row of its own and is being described by
        # the defaults — which the panel says out loud rather than implying.
        "is_configured": policy is not None,
        "updated_at": policy.updated_at.isoformat() if policy else None,
        "rules": [
            {
                "subject_kind": rule.subject_kind,
                "surface": rule.surface,
                "method_key": rule.method_key,
                "is_enabled": rule.is_enabled,
                "enabled_at": (
                    rule.enabled_at.isoformat() if rule.enabled_at else None
                ),
                "notes": rule.notes,
            }
            for rule in rules
        ],
    }


def set_family_access_mode(
    tenant_id: str, mode: str, *, updated_by_user_id: str = None
) -> TenantAuthPolicy:
    """Choose whether parents sign in as themselves or as their child.

    ADR-011's setting, and the switch that decides whether a parent is an
    authentication subject at all. It is not a method — no rule is written and
    no method is enabled or disabled here — which is why it lives beside
    `set_method` rather than inside it.

    **Turning it on provisions nobody.** It makes a parent login *possible*;
    each one is still issued deliberately. **Turning it off destroys nothing**
    — accounts, credentials, identifiers, sessions and family relationships
    all survive, and the parent simply stops being a parent authentication
    subject. That is the expand-before-contract rule, and a policy change that
    deleted identity would be the worst kind of surprise.
    """
    from core.school_time import utc_now

    if mode not in FAMILY_ACCESS_MODES:
        raise ValueError(
            f"Unknown family access mode {mode!r}. Expected one of: "
            + ", ".join(FAMILY_ACCESS_MODES)
        )

    policy = ensure_default_policy(tenant_id, updated_by_user_id=updated_by_user_id)
    policy.family_access_mode = mode
    policy.updated_by_user_id = updated_by_user_id
    policy.updated_at = utc_now()
    db.session.flush()
    return policy


def set_student_credential_policy(
    tenant_id: str, mode: str, *, updated_by_user_id: str = None
) -> TenantAuthPolicy:
    """Whether a school-issued student credential must be replaced on first use.

    Read at issuance, so changing it governs the credentials issued from now
    on and leaves live ones alone — a school tightening its policy does not
    lock every child out of the account they already have.
    """
    from core.school_time import utc_now

    if mode not in STUDENT_CREDENTIAL_POLICIES:
        raise ValueError(
            f"Unknown student credential policy {mode!r}. Expected one of: "
            + ", ".join(STUDENT_CREDENTIAL_POLICIES)
        )

    policy = ensure_default_policy(tenant_id, updated_by_user_id=updated_by_user_id)
    policy.student_credential_policy = mode
    policy.updated_by_user_id = updated_by_user_id
    policy.updated_at = utc_now()
    db.session.flush()
    return policy


def set_method(
    tenant_id: str,
    subject_kind: str,
    method_key: str,
    *,
    enabled: bool,
    surface: str = SURFACE_ANY,
    updated_by_user_id: str = None,
    notes: str = None,
):
    """Turn one authentication method on or off for one kind of person.

    Service-level rather than an API: the panel shows the policy read-only,
    deliberately, and an operator changing it does so through a considered
    action rather than a toggle sitting next to a school's name. A mutation
    endpoint and its screen belong to the phase that designs them.

    A disabled rule is written rather than deleted, so the record of somebody
    having decided against a method survives — which is most of what makes
    this a table rather than a JSON bag.
    """
    from core.school_time import utc_now

    if subject_kind not in SUBJECT_KINDS:
        raise ValueError(f"Unknown subject kind {subject_kind!r}.")

    from .strategies import registry

    if method_key not in registry:
        raise ValueError(
            f"Unknown authentication method {method_key!r}. "
            f"Known: {registry.keys()}."
        )

    # A school being given its first explicit rule needs the policy row that
    # says it has been configured at all — see `allowed_methods`.
    ensure_default_policy(tenant_id, updated_by_user_id=updated_by_user_id)

    rule = (
        db.session.query(TenantAuthPolicyRule)
        .filter(
            TenantAuthPolicyRule.tenant_id == tenant_id,
            TenantAuthPolicyRule.subject_kind == subject_kind,
            TenantAuthPolicyRule.surface == surface,
            TenantAuthPolicyRule.method_key == method_key,
        )
        .first()
    )
    if rule is None:
        rule = TenantAuthPolicyRule(
            tenant_id=tenant_id,
            subject_kind=subject_kind,
            surface=surface,
            method_key=method_key,
        )
        db.session.add(rule)

    rule.is_enabled = bool(enabled)
    rule.enabled_by_user_id = updated_by_user_id
    rule.enabled_at = utc_now() if enabled else None
    if notes is not None:
        rule.notes = notes

    db.session.flush()

    if not enabled:
        end_sessions_opened_with(
            tenant_id, method_key, actor_user_id=updated_by_user_id
        )

    return rule


def end_sessions_opened_with(
    tenant_id: str, method_key: str, *, actor_user_id: str = None
) -> int:
    """Sign out everyone who is inside by a door the school has just closed.

    Turning a method off has to mean something today. Without this, a school
    that disables PIN sign-in after a leak has stopped the *next* sign-in and
    left every current one running for as long as its session lives — the
    method is off on the screen and on for the people already through it,
    which is the opposite of what was asked for.

    Only sessions opened *with* that method end. Somebody who signed in with
    their password is unaffected, even if they also hold a PIN: the decision
    was about a way in, not about a person.

    Each candidate is re-tested with `is_method_allowed` rather than by
    re-deriving who the rule covers, so subject kind and surface are read the
    one way the pipeline reads them. A rule that turns out not to cover an
    account — one kind disabled while another keeps the method — leaves that
    account's session alone.
    """
    from core.authentication import load_without_tenant_scope
    from core.school_time import utc_now

    from .event_models import record_event
    from .models import Session, User

    sessions = load_without_tenant_scope(
        lambda: Session.query.filter(
            Session.tenant_id == tenant_id,
            Session.login_method == method_key,
            Session.revoked.is_(False),
        ).all()
    )

    ended_ids = []
    for session in sessions:
        account = load_without_tenant_scope(
            lambda: User.query.filter_by(id=session.user_id).first()
        )
        if account is None or is_method_allowed(account, method_key):
            continue

        session.revoked = True
        session.revoked_at = utc_now()
        ended_ids.append(session.id)

        record_event(
            event_type="session_ended_by_policy",
            tenant_id=tenant_id,
            account_id=account.id,
            actor_user_id=actor_user_id,
            method_key=method_key,
            reason="method_disabled",
            session_id=session.id,
        )

    if ended_ids:
        from .tokens import revoke_session_tokens

        for session_id in ended_ids:
            revoke_session_tokens(session_id)

    db.session.flush()
    return len(ended_ids)


def published_auth_methods(tenant_id: str) -> List[str]:
    """The methods a school's sign-in screen may offer.

    The union across every kind of person the school has, and nothing finer.
    Which methods a school offers is not a secret — it is visible on the login
    page — but which method a *particular* human may use is, so this is never
    asked per account and the endpoint that serves it is unauthenticated by
    design.

    A school with no policy row of its own is described by the default, the
    same way `allowed_methods` treats one.
    """
    if policy_for(tenant_id) is None:
        return [DEFAULT_METHOD_KEY]
    return sorted(methods_declared_for(tenant_id))
