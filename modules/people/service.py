"""People domain services.

Holds one structural guarantee: an account always belongs to a person.

The platform creates accounts from a dozen places — registration, admissions,
staff onboarding, bulk imports, seed scripts — and "remember to create a Person
too" at every one of them is a rule that will eventually be forgotten. It is
enforced here instead, in the same spirit as the tenant scoping that already
guards every query.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import event
from sqlalchemy.orm import Session

from .models import (
    FAMILY_ROLE_AUNT,
    FAMILY_ROLE_BROTHER,
    FAMILY_ROLE_FATHER,
    FAMILY_ROLE_GRANDFATHER,
    FAMILY_ROLE_GRANDMOTHER,
    FAMILY_ROLE_GUARDIAN,
    FAMILY_ROLE_MOTHER,
    FAMILY_ROLE_SISTER,
    FAMILY_ROLE_UNCLE,
    Person,
)

# Schools type the relationship in free text. Recognising the common ones keeps
# a father recorded as a guardian from being treated as a different kind of
# person than a father recorded as a father.
_WRITTEN_RELATIONSHIPS = {
    "father": FAMILY_ROLE_FATHER,
    "dad": FAMILY_ROLE_FATHER,
    "papa": FAMILY_ROLE_FATHER,
    "mother": FAMILY_ROLE_MOTHER,
    "mom": FAMILY_ROLE_MOTHER,
    "mum": FAMILY_ROLE_MOTHER,
    "mummy": FAMILY_ROLE_MOTHER,
    "grandfather": FAMILY_ROLE_GRANDFATHER,
    "grandmother": FAMILY_ROLE_GRANDMOTHER,
    "uncle": FAMILY_ROLE_UNCLE,
    "aunt": FAMILY_ROLE_AUNT,
    "brother": FAMILY_ROLE_BROTHER,
    "sister": FAMILY_ROLE_SISTER,
}


def family_role_for(written_relationship: Optional[str]) -> str:
    """Map what the school wrote to a family relationship.

    Anything unrecognised is a guardian: the school has told us this person is
    responsible for the student, which is the part that matters.
    """
    return _WRITTEN_RELATIONSHIPS.get(
        (written_relationship or "").strip().lower(), FAMILY_ROLE_GUARDIAN
    )


def fill_blank_identity(person: Person, values: dict) -> bool:
    """Fill only what the Person does not already know. Never overwrites."""
    changed = False
    for field, value in values.items():
        if value is not None and getattr(person, field, None) is None:
            setattr(person, field, value)
            changed = True
    return changed


def _fill_employment_gaps(staff, employment: dict):
    """Existing employment is not overwritten by a later form; only gaps filled."""
    for field, value in employment.items():
        if value is not None and getattr(staff, field, None) is None:
            setattr(staff, field, value)
    return staff


def ensure_staff(tenant_id: str, person_id: str, **employment):
    """The Staff relationship for a person, created if they have none.

    Employment is created once per person (ADR-001); someone who already works
    here and starts teaching keeps the employment they had.
    """
    from .employment import Staff

    staff = Staff.query.filter_by(tenant_id=tenant_id, person_id=person_id).first()
    if staff is None:
        staff = Staff(tenant_id=tenant_id, person_id=person_id, **employment)
        db_session_add(staff)
        return staff

    return _fill_employment_gaps(staff, employment)


def employment_status_for_legacy_flag(legacy_status: Optional[str]) -> str:
    """Translate the v1 active/inactive flag into a business state.

    v1 recorded only whether someone was active, so a departure cannot be
    reported as a resignation, retirement or dismissal without inventing a fact.
    'Left' says exactly what is known: they have gone, and the reason was never
    recorded.
    """
    from .employment import EMPLOYMENT_STATUS_LEFT, EMPLOYMENT_STATUS_WORKING

    if (legacy_status or "").strip().lower() == "active":
        return EMPLOYMENT_STATUS_WORKING
    return EMPLOYMENT_STATUS_LEFT


def ensure_employment_period(staff, joined_on=None):
    """The employment period a staff member is currently serving.

    Opened once when they join. Someone who leaves and returns gets a second
    period, which is a separate business event rather than a side effect of
    filling in a form.
    """
    from .employment import StaffEmploymentPeriod

    period = StaffEmploymentPeriod.query.filter_by(staff_id=staff.id).first()
    if period is not None:
        return period

    period = StaffEmploymentPeriod(
        tenant_id=staff.tenant_id, staff_id=staff.id, joined_on=joined_on
    )
    db_session_add(period)
    return period


def db_session_add(instance) -> None:
    """Add and flush, so the caller immediately has an id to reference."""
    from core.database import db

    db.session.add(instance)
    db.session.flush()


def name_for_account(user) -> str:
    """A person must have a name; derive one when the account carries none."""
    if getattr(user, "name", None) and user.name.strip():
        return user.name.strip()
    email = getattr(user, "email", None)
    if email and "@" in email:
        return email.split("@", 1)[0]
    return "Unnamed"


def build_person_for_account(user) -> Person:
    """The Person an account implies, from what the account itself knows.

    Only identity the account carries is copied. Anything the school knows
    elsewhere — a student's date of birth, a teacher's address — is filled in by
    whoever owns that information.
    """
    return Person(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        full_name=name_for_account(user),
        email=getattr(user, "email", None),
        photo_url=getattr(user, "profile_picture_url", None),
    )


def _pending_account(session, user_id: str):
    """The account with this id, whether already saved or still being saved."""
    from modules.auth.models import User

    for pending in session.new:
        if isinstance(pending, User) and pending.id == user_id:
            return pending
    return session.get(User, user_id) if user_id else None


def _person_behind(session, instance):
    """The human whose account this relationship was created for."""
    account = _pending_account(session, getattr(instance, "user_id", None))
    return getattr(account, "person", None) if account is not None else None


@event.listens_for(Session, "before_flush")
def _relationships_belong_to_people(session, flush_context, instances) -> None:
    """Attach every arriving record to the human it describes.

    An account gets the Person it belongs to, a student relationship gets that
    same Person, and teaching gets the employment it is a participation of
    (ADR-005). Assigning relationships rather than ids is what orders each
    insert ahead of the row referencing it.

    Autoflush is suspended because resolving these may read the database, and a
    flush inside a flush would recurse.
    """
    # Imported here: this module loads while the models are still being defined.
    from modules.auth.models import User
    from modules.students.models import Student
    from modules.teachers.models import Teacher

    with session.no_autoflush:
        # Accounts first: the records below borrow the Person created here.
        for instance in session.new:
            if isinstance(instance, User) and not instance.person_id:
                if not instance.tenant_id:
                    # Nothing to attach a person to; the account is invalid and
                    # will fail its own constraint.
                    continue
                instance.person = build_person_for_account(instance)

        for instance in session.new:
            if isinstance(instance, Student) and not instance.person_id:
                instance.person = _person_behind(session, instance)

            elif isinstance(instance, Teacher) and not instance.staff_id:
                person = _person_behind(session, instance)
                if person is not None:
                    instance.staff = _employment_for(session, instance, person)


def _employment_for(session, teacher, person):
    """The employment a teaching record participates in, opened if there is none."""
    from .employment import Staff

    employment = (
        session.query(Staff)
        .filter_by(tenant_id=teacher.tenant_id, person_id=person.id)
        .first()
    )
    if employment is not None:
        return _fill_employment_gaps(
            employment,
            {
                "employee_number": getattr(teacher, "employee_id", None),
                "designation": getattr(teacher, "designation", None),
                "department_id": getattr(teacher, "department_id", None),
            },
        )

    # No flush here: this runs inside one, so rows are added and ordered by
    # their relationships instead.
    from .employment import EMPLOYMENT_STATUS_WORKING, StaffEmploymentPeriod

    status = employment_status_for_legacy_flag(getattr(teacher, "status", None))
    employment = Staff(
        tenant_id=teacher.tenant_id,
        person=person,
        employee_number=getattr(teacher, "employee_id", None),
        designation=getattr(teacher, "designation", None),
        department_id=getattr(teacher, "department_id", None),
        employment_status=status,
    )
    session.add(employment)

    # Employment always covers a period; someone who works here started
    # sometime, even where the date was never recorded.
    session.add(
        StaffEmploymentPeriod(
            tenant_id=teacher.tenant_id,
            staff=employment,
            joined_on=getattr(teacher, "date_of_joining", None),
            end_reason=None if status == EMPLOYMENT_STATUS_WORKING else status,
        )
    )
    return employment
