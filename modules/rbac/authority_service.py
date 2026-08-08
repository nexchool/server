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

from sqlalchemy import event
from sqlalchemy.orm import Session as OrmSession

from core.database import db

from .models import AuthorityDelegation, Role, StaffAuthority
from core.school_time import school_today


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

    # A profile belongs to the organization that defined it; holding one from
    # elsewhere would be authority in a school this person has nothing to do with.
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

    today = on_date or school_today()

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


RELATIONSHIP_STUDENT = "student"


def _roles_from_employment(person_id: str, on_date: Optional[date]) -> List[Role]:
    """Authority held, or acted under, through employment.

    Nothing once the employment has ended or while the person is suspended.
    That is the point of ADR-013: authority stops because the employment
    stopped, not because somebody remembered to withdraw it.
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
    return roles


def _roles_implied_by_relationships(person_id: str) -> List[Role]:
    """Authority that follows from what someone *is*, rather than being granted.

    A student was never given the right to see their own attendance; it comes
    with being a student. So it is derived from the relationship and disappears
    with it, instead of being assigned account by account and left behind.
    """
    from modules.people.models import Person
    from modules.students.models import Student

    person = Person.query.get(person_id)
    if person is None:
        return []

    implied = []
    if Student.query.filter_by(person_id=person_id).first() is not None:
        implied.append(RELATIONSHIP_STUDENT)

    if not implied:
        return []

    return (
        Role.query.filter(
            Role.tenant_id == person.tenant_id,
            Role.implied_by_relationship.in_(implied),
        ).all()
    )


def authority_profiles_for_person(
    person_id: str, on_date: Optional[date] = None
) -> List[Role]:
    """Every Authority Profile this person holds, however they come to hold it.

    Three sources: authority they hold through employment, authority they are
    acting under for someone else, and authority implied by who they are.
    """
    roles = _roles_from_employment(person_id, on_date)
    roles.extend(_roles_implied_by_relationships(person_id))

    by_id = {role.id: role for role in roles}
    return sorted(by_id.values(), key=lambda role: role.name)


def permission_keys_for_person(
    person_id: str, on_date: Optional[date] = None
) -> List[str]:
    """Every permission key this person holds."""
    keys = set()
    for role in authority_profiles_for_person(person_id, on_date):
        for permission in role.permissions:
            keys.add(permission.name)
    return sorted(keys)


def user_ids_holding_profiles(
    tenant_id: str,
    role_names,
    *,
    must_be_able_to_act: bool = False,
) -> set:
    """Accounts whose person holds any of these Authority Profiles.

    The one way to ask "who are the Admins / Teachers / Students?", whether the
    caller wants an audience or a list of people to act. Answered from the same
    two sources as authorization: profiles held through employment, and profiles
    a business relationship implies.

    Matching is case-insensitive because callers ask for "Admin" and "admin"
    interchangeably.

    Set ``must_be_able_to_act`` when the answer is a list of people expected to
    do something — a suspended member of staff should not be asked.
    """
    from sqlalchemy import func

    from modules.auth.models import User
    from modules.people.employment import (
        AUTHORITY_BEARING_STATUSES,
        EMPLOYED_STATUSES,
        Staff,
    )
    from modules.students.models import Student

    from .models import StaffAuthority

    wanted = [str(name).lower() for name in role_names if name]
    if not wanted:
        return set()

    profiles = Role.query.filter(
        Role.tenant_id == tenant_id, func.lower(Role.name).in_(wanted)
    ).all()
    if not profiles:
        return set()

    usable = AUTHORITY_BEARING_STATUSES if must_be_able_to_act else EMPLOYED_STATUSES
    holders = {
        user_id
        for (user_id,) in db.session.query(User.id)
        .join(Staff, Staff.person_id == User.person_id)
        .join(StaffAuthority, StaffAuthority.staff_id == Staff.id)
        .filter(
            User.tenant_id == tenant_id,
            Staff.tenant_id == tenant_id,
            StaffAuthority.role_id.in_([profile.id for profile in profiles]),
            Staff.employment_status.in_(list(usable)),
        )
        .all()
    }

    # Nobody is assigned the student profile; holding the relationship is what
    # makes someone a student.
    if any(p.implied_by_relationship == RELATIONSHIP_STUDENT for p in profiles):
        holders.update(
            user_id
            for (user_id,) in db.session.query(User.id)
            .join(Student, Student.person_id == User.person_id)
            .filter(User.tenant_id == tenant_id, Student.tenant_id == tenant_id)
            .all()
        )

    return holders


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


@event.listens_for(OrmSession, "after_flush")
def _a_change_of_standing_forgets_cached_authority(session, flush_context) -> None:
    """Suspending or ending an employment takes effect on the next request.

    What a person may do is resolved from their employment (ADR-013), so
    `employment_status` decides authority just as surely as a granted profile
    does — `may_act` withholds it from anyone suspended. The cache was only
    ever dropped when the *grant* changed, which meant a suspension took
    effect whenever the entry happened to expire. Two minutes of a suspended
    employee still being able to act is the whole reason suspension exists.

    A listener rather than a call in each writer: status is set from
    `employ()`, from the v1 flag translation, from bulk teacher updates, and
    from the resignation and retirement workflows still to come. That is the
    same argument that put the account-person rule in a listener.

    Dropping a cache entry is safe if the transaction later rolls back — the
    next read simply reloads it.
    """
    from modules.people.employment import Staff

    with session.no_autoflush:
        for instance in session.dirty:
            if not isinstance(instance, Staff):
                continue
            standing = db.inspect(instance).attrs.employment_status.history
            if standing.has_changes():
                _forget_cached_permissions_for(instance)
