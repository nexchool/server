"""Business Authority — what an employed person is trusted to do (ADR-013).

Schools do not think in permissions. They decide that someone *is* the
Examination Coordinator, and the authority follows from that decision. This
module holds that side of authorization: granting an Authority Profile to an
employment, withdrawing it, and answering which permission keys it implies.

Whether a particular request may proceed is decided elsewhere, against the
permission keys these authorities expand to.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from core.database import db

from .models import AuthorityDelegation, Role, StaffAuthority


class AuthorityRefused(Exception):
    """The authority cannot be granted as asked."""


def grant_authority(
    staff_id: str,
    role_id: str,
    *,
    granted_by_user_id: Optional[str] = None,
) -> StaffAuthority:
    """Record that an employed person holds an Authority Profile.

    Granting to someone who no longer works here is refused rather than
    recorded: authority is an aspect of employment, so there is nothing for it
    to be an aspect of.
    """
    from modules.people.employment import Staff

    employment = Staff.query.get(staff_id)
    if employment is None:
        raise AuthorityRefused("That employment does not exist.")
    if not employment.is_employed:
        raise AuthorityRefused(
            "That person no longer works here, so they cannot hold authority."
        )

    role = Role.query.get(role_id)
    if role is None or role.tenant_id != employment.tenant_id:
        raise AuthorityRefused("That authority profile does not exist here.")

    existing = StaffAuthority.query.filter_by(
        staff_id=staff_id, role_id=role_id
    ).first()
    if existing is not None:
        return existing

    authority = StaffAuthority(
        tenant_id=employment.tenant_id,
        staff_id=staff_id,
        role_id=role_id,
        granted_by_user_id=granted_by_user_id,
    )
    db.session.add(authority)
    db.session.flush()

    _forget_cached_permissions_for(employment)
    return authority


def withdraw_authority(staff_id: str, role_id: str) -> bool:
    """Withdraw an Authority Profile. Returns whether anything was held."""
    from modules.people.employment import Staff

    authority = StaffAuthority.query.filter_by(
        staff_id=staff_id, role_id=role_id
    ).first()
    if authority is None:
        return False

    db.session.delete(authority)
    db.session.flush()

    _forget_cached_permissions_for(Staff.query.get(staff_id))
    return True


def authorities_held_by(staff_id: str) -> List[Role]:
    """The Authority Profiles this employment holds."""
    return (
        db.session.query(Role)
        .join(StaffAuthority, StaffAuthority.role_id == Role.id)
        .filter(StaffAuthority.staff_id == staff_id)
        .all()
    )


def delegate_authority(
    role_id: str,
    from_staff_id: str,
    to_staff_id: str,
    *,
    effective_from: date,
    effective_to: date,
    reason: Optional[str] = None,
    created_by_user_id: Optional[str] = None,
) -> AuthorityDelegation:
    """Lend an Authority Profile to someone else for a period.

    The school's usual case: a principal goes on leave and the vice principal
    acts in their place until they return.

    Only authority actually held can be lent — you cannot delegate what you do
    not have — and it can only be lent to someone able to act.
    """
    from modules.people.employment import Staff

    if from_staff_id == to_staff_id:
        raise AuthorityRefused("Authority cannot be delegated to the same person.")
    if effective_to < effective_from:
        raise AuthorityRefused("A delegation cannot end before it begins.")

    delegator = Staff.query.get(from_staff_id)
    delegate = Staff.query.get(to_staff_id)
    if delegator is None or delegate is None:
        raise AuthorityRefused("Both employments must exist.")
    if delegator.tenant_id != delegate.tenant_id:
        raise AuthorityRefused("Authority cannot be delegated between organizations.")

    held = StaffAuthority.query.filter_by(
        staff_id=from_staff_id, role_id=role_id
    ).first()
    if held is None:
        raise AuthorityRefused("That authority is not held, so it cannot be delegated.")

    if not delegate.may_act:
        raise AuthorityRefused(
            "That person cannot act on the organization's behalf, so authority "
            "cannot be delegated to them."
        )

    delegation = AuthorityDelegation(
        tenant_id=delegator.tenant_id,
        role_id=role_id,
        from_staff_id=from_staff_id,
        to_staff_id=to_staff_id,
        effective_from=effective_from,
        effective_to=effective_to,
        reason=reason,
        created_by_user_id=created_by_user_id,
    )
    db.session.add(delegation)
    db.session.flush()

    _forget_cached_permissions_for(delegate)
    return delegation


def end_delegation(delegation_id: str) -> bool:
    """End a delegation before its date. Returns whether one was running."""
    from modules.people.employment import Staff

    delegation = AuthorityDelegation.query.get(delegation_id)
    if delegation is None or delegation.revoked_at is not None:
        return False

    delegation.revoked_at = datetime.now(timezone.utc)
    db.session.flush()

    _forget_cached_permissions_for(Staff.query.get(delegation.to_staff_id))
    return True


def delegations_in_effect_for(staff_id: str, on_date: Optional[date] = None):
    """Delegations this employment is currently acting under.

    Expiry is a property of this query rather than a job that must run: a
    delegation simply stops being read once its window has passed.

    A delegation also lapses if the person who lent it has left the
    organization — their authority ended, so there is nothing left to lend.
    Their being on leave or suspended does not lapse it, since that absence is
    usually the reason the delegation exists.
    """
    from modules.people.employment import Staff

    today = on_date or date.today()

    delegations = (
        db.session.query(AuthorityDelegation)
        .filter(
            AuthorityDelegation.to_staff_id == staff_id,
            AuthorityDelegation.revoked_at.is_(None),
            AuthorityDelegation.effective_from <= today,
            AuthorityDelegation.effective_to >= today,
        )
        .all()
    )

    in_effect = []
    for delegation in delegations:
        delegator = Staff.query.get(delegation.from_staff_id)
        if delegator is not None and delegator.is_employed:
            in_effect.append(delegation)
    return in_effect


def permission_keys_for_person(
    person_id: str, on_date: Optional[date] = None
) -> List[str]:
    """Permission keys this person holds through their employment.

    Two sources: the authority they hold themselves, and any they are acting
    under on behalf of someone else.

    Nothing is returned once the employment has ended, or while the person is
    suspended. That is the point of ADR-013: authority stops because the
    employment stopped, not because somebody remembered to withdraw it.
    """
    from modules.people.employment import Staff

    employment = Staff.query.filter_by(person_id=person_id).first()
    if employment is None or not employment.may_act:
        return []

    roles = list(authorities_held_by(employment.id))
    roles.extend(
        delegation.role
        for delegation in delegations_in_effect_for(employment.id, on_date)
        if delegation.role is not None
    )

    keys = set()
    for role in roles:
        for permission in role.permissions:
            keys.add(permission.name)
    return sorted(keys)


def _forget_cached_permissions_for(employment) -> None:
    """Drop the cached permission set of whoever holds this employment.

    Authority changes must be felt on the next request, not when a cache
    happens to expire.
    """
    if employment is None:
        return

    from modules.auth.models import User
    from .services import invalidate_user_permissions

    for account in User.query.filter_by(person_id=employment.person_id).all():
        invalidate_user_permissions(account.id)
