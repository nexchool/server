"""Business Authority — what an employed person is trusted to do (ADR-013).

Schools do not think in permissions. They decide that someone *is* the
Examination Coordinator, and the authority follows from that decision. This
module holds that side of authorization: granting an Authority Profile to an
employment, withdrawing it, and answering which permission keys it implies.

Whether a particular request may proceed is decided elsewhere, against the
permission keys these authorities expand to.
"""

from __future__ import annotations

from typing import List, Optional

from core.database import db

from .models import Role, StaffAuthority


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


def permission_keys_for_person(person_id: str) -> List[str]:
    """Permission keys this person holds through their employment.

    Nothing is returned once the employment has ended, or while the person is
    suspended. That is the point of ADR-013: authority stops because the
    employment stopped, not because somebody remembered to withdraw it.
    """
    from modules.people.employment import Staff

    employment = Staff.query.filter_by(person_id=person_id).first()
    if employment is None or not employment.may_act:
        return []

    keys = set()
    for role in authorities_held_by(employment.id):
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
