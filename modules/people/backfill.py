"""Build the People model from v1 data (ADR-010).

Three things happen, in order:

1. Every user account gets a Person, enriched with whatever the student or
   teacher row knows about that human.
2. The father and mother columns on each student become People, merged across
   students where the evidence is conclusive.
3. Students that share a parent set become one Family.

The pass is idempotent: it reads what already exists first, so running it twice
changes nothing the second time.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from core.database import db

from .matching import (
    PersonMatchKey,
    build_match_key,
    normalize_name,
    normalize_phone,
)
from .employment import (
    EMPLOYMENT_STATUS_LEFT,
    EMPLOYMENT_STATUS_WORKING,
    Staff,
    StaffEmploymentPeriod,
)
from .models import (
    FAMILY_ROLE_CHILD,
    FAMILY_ROLE_FATHER,
    FAMILY_ROLE_MOTHER,
    Family,
    FamilyMember,
    Person,
)
from .service import (
    build_person_for_account,
    employment_status_for_legacy_flag,
    family_role_for,
    fill_blank_identity,
)

logger = logging.getLogger(__name__)


@dataclass
class BackfillReport:
    """What one run did, and what it declined to decide."""

    tenant_id: str
    people_created: int = 0
    people_enriched: int = 0
    accounts_linked: int = 0
    parents_created: int = 0
    parents_merged: int = 0
    families_created: int = 0
    memberships_created: int = 0
    students_linked: int = 0
    staff_created: int = 0
    teachers_linked: int = 0
    suggestions: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"tenant={self.tenant_id} people={self.people_created} "
            f"enriched={self.people_enriched} "
            f"accounts_linked={self.accounts_linked} parents={self.parents_created} "
            f"merged={self.parents_merged} families={self.families_created} "
            f"memberships={self.memberships_created} students={self.students_linked} "
            f"staff={self.staff_created} teachers={self.teachers_linked} "
            f"suggestions={len(self.suggestions)}"
        )


def _link_accounts_to_people(tenant_id: str, report: BackfillReport) -> Dict[str, str]:
    """Give every account a Person, carrying across what v1 knew about them.

    Accounts created since the People model arrived already have a Person, built
    from what the account itself knew. Those are enriched here rather than
    skipped: the student and teacher rows hold identity — date of birth, phone,
    address — that the account never saw.
    """
    from modules.auth.models import User
    from modules.students.models import Student
    from modules.teachers.models import Teacher

    users = User.query.filter(User.tenant_id == tenant_id).all()
    students_by_user = {
        student.user_id: student
        for student in Student.query.filter(Student.tenant_id == tenant_id).all()
    }
    teachers_by_user = {
        teacher.user_id: teacher
        for teacher in Teacher.query.filter(Teacher.tenant_id == tenant_id).all()
    }

    person_by_user: Dict[str, str] = {}

    for user in users:
        student = students_by_user.get(user.id)
        teacher = teachers_by_user.get(user.id)

        known = {
            "date_of_birth": getattr(student, "date_of_birth", None),
            "gender": getattr(student, "gender", None),
            "phone_number": (
                getattr(student, "phone", None) or getattr(teacher, "phone", None)
            ),
            "address": (
                getattr(student, "address", None) or getattr(teacher, "address", None)
            ),
            "aadhaar_number": getattr(student, "aadhar_number", None),
        }

        if user.person_id:
            person = Person.query.get(user.person_id)
            if person is not None and fill_blank_identity(person, known):
                report.people_enriched += 1
        else:
            person = build_person_for_account(user)
            for field, value in known.items():
                setattr(person, field, value)
            db.session.add(person)
            db.session.flush()
            user.person_id = person.id
            report.people_created += 1
            report.accounts_linked += 1

        person_by_user[user.id] = user.person_id

    return person_by_user




def _link_students_to_people(
    tenant_id: str, person_by_user: Dict[str, str], report: BackfillReport
) -> None:
    """Point each student relationship at the human it belongs to."""
    from modules.students.models import Student

    for student in Student.query.filter(
        Student.tenant_id == tenant_id, Student.person_id.is_(None)
    ).all():
        person_id = person_by_user.get(student.user_id)
        if person_id is None:
            continue
        student.person_id = person_id
        report.students_linked += 1


def _create_staff_relationships(
    tenant_id: str, person_by_user: Dict[str, str], report: BackfillReport
) -> None:
    """Give every employed person a Staff relationship.

    Teachers bring employment detail with them. Everyone else who holds an
    account and is not a student is staff too — an administrator or a
    receptionist is employed just as a teacher is — even though v1 recorded
    nothing about their employment.
    """
    from modules.auth.models import User
    from modules.students.models import Student
    from modules.teachers.models import Teacher

    student_user_ids = {
        student.user_id
        for student in Student.query.filter(Student.tenant_id == tenant_id).all()
    }
    teachers_by_user = {
        teacher.user_id: teacher
        for teacher in Teacher.query.filter(Teacher.tenant_id == tenant_id).all()
    }
    people_with_staff = {
        staff.person_id
        for staff in Staff.query.filter(Staff.tenant_id == tenant_id).all()
    }

    for user in User.query.filter(User.tenant_id == tenant_id).all():
        # Platform administrators run Nexchool; they are not employed by the
        # school whose data they are looking at.
        if user.is_platform_admin or user.id in student_user_ids:
            continue

        person_id = person_by_user.get(user.id)
        if person_id is None or person_id in people_with_staff:
            continue

        teacher = teachers_by_user.get(user.id)
        status = employment_status_for_legacy_flag(
            getattr(teacher, "status", None) if teacher else "active"
        )

        staff = Staff(
            tenant_id=tenant_id,
            person_id=person_id,
            employee_number=getattr(teacher, "employee_id", None),
            designation=getattr(teacher, "designation", None),
            department_id=getattr(teacher, "department_id", None),
            employment_status=status,
        )
        db.session.add(staff)
        db.session.flush()

        db.session.add(
            StaffEmploymentPeriod(
                tenant_id=tenant_id,
                staff_id=staff.id,
                joined_on=getattr(teacher, "date_of_joining", None),
                # v1 never recorded a leaving date, so a closed period carries
                # its reason instead of a date it does not know.
                end_reason=None if status == EMPLOYMENT_STATUS_WORKING else status,
            )
        )
        people_with_staff.add(person_id)
        report.staff_created += 1

    db.session.flush()


def _link_teachers_to_staff(
    tenant_id: str, person_by_user: Dict[str, str], report: BackfillReport
) -> None:
    """Attach each teaching record to the employment it is a participation of.

    Teaching describes what an employed person does academically (ADR-005), so
    it hangs off the Staff relationship rather than off the login.
    """
    from modules.teachers.models import Teacher

    staff_by_person = {
        staff.person_id: staff.id
        for staff in Staff.query.filter(Staff.tenant_id == tenant_id).all()
    }

    for teacher in Teacher.query.filter(
        Teacher.tenant_id == tenant_id, Teacher.staff_id.is_(None)
    ).all():
        person_id = person_by_user.get(teacher.user_id)
        staff_id = staff_by_person.get(person_id) if person_id else None
        if staff_id is None:
            continue
        teacher.staff_id = staff_id
        report.teachers_linked += 1

    db.session.flush()


def _existing_parent_index(tenant_id: str) -> Dict[PersonMatchKey, str]:
    """Rebuild the merge index from People already recorded as parents.

    This is what makes a second run a no-op instead of a duplicate-maker.
    """
    index: Dict[PersonMatchKey, str] = {}

    rows = (
        db.session.query(FamilyMember, Person)
        .join(Person, Person.id == FamilyMember.person_id)
        .filter(FamilyMember.tenant_id == tenant_id)
        .all()
    )
    for membership, person in rows:
        key = build_match_key(
            role=membership.relationship,
            name=person.full_name,
            phone=person.phone_number,
            email=person.email,
        )
        if key is not None:
            index[key] = person.id

    return index


def _resolve_parent(
    tenant_id: str,
    role: str,
    name: Optional[str],
    phone: Optional[str],
    email: Optional[str],
    occupation: Optional[str],
    index: Dict[PersonMatchKey, str],
    report: BackfillReport,
) -> Optional[str]:
    """Find or create the Person for one parent column set."""
    if not name or not name.strip():
        return None

    key = build_match_key(role=role, name=name, phone=phone, email=email)

    if key is not None and key in index:
        report.parents_merged += 1
        return index[key]

    person = Person(
        tenant_id=tenant_id,
        full_name=name.strip(),
        phone_number=phone,
        email=email,
        occupation=occupation,
    )
    db.session.add(person)
    db.session.flush()

    report.people_created += 1
    report.parents_created += 1

    if key is not None:
        index[key] = person.id
    else:
        # Not enough to merge on now, but a human may still recognise it later.
        report.suggestions.append(
            {
                "reason": "parent_without_contact_details",
                "person_id": person.id,
                "name": name,
                "role": role,
            }
        )

    return person.id


def _record_weak_matches(
    students: List[Any], report: BackfillReport
) -> None:
    """Flag parents who share a phone but were not merged, for human review."""
    by_phone: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    for student in students:
        for role, name, phone in (
            (FAMILY_ROLE_FATHER, student.father_name, student.father_phone),
            (FAMILY_ROLE_MOTHER, student.mother_name, student.mother_phone),
            (
                family_role_for(student.guardian_relationship),
                student.guardian_name,
                student.guardian_phone,
            ),
        ):
            normalized_phone = normalize_phone(phone)
            normalized_name = normalize_name(name)
            if normalized_phone and normalized_name:
                by_phone[(role, normalized_phone)].add(normalized_name)

    for (role, phone), names in by_phone.items():
        if len(names) > 1:
            report.suggestions.append(
                {
                    "reason": "same_phone_different_name",
                    "role": role,
                    "phone": phone,
                    "names": sorted(names),
                }
            )


def backfill_tenant(tenant_id: str) -> BackfillReport:
    """Build People, Families and memberships for one organization."""
    from modules.students.models import Student

    report = BackfillReport(tenant_id=tenant_id)

    person_by_user = _link_accounts_to_people(tenant_id, report)
    _link_students_to_people(tenant_id, person_by_user, report)
    _create_staff_relationships(tenant_id, person_by_user, report)
    _link_teachers_to_staff(tenant_id, person_by_user, report)
    parent_index = _existing_parent_index(tenant_id)

    students = Student.query.filter(Student.tenant_id == tenant_id).all()
    _record_weak_matches(students, report)

    # Students already placed in a family were handled by an earlier run.
    already_placed = {
        membership.person_id
        for membership in FamilyMember.query.filter(
            FamilyMember.tenant_id == tenant_id,
            FamilyMember.relationship == FAMILY_ROLE_CHILD,
        ).all()
    }

    # Siblings are students whose parents resolve to the same set of People.
    families_by_parents: Dict[frozenset, str] = {}

    for student in students:
        child_person_id = person_by_user.get(student.user_id)
        if child_person_id is None or child_person_id in already_placed:
            continue

        parents: List[Tuple[str, str]] = []

        father_id = _resolve_parent(
            tenant_id,
            FAMILY_ROLE_FATHER,
            student.father_name,
            student.father_phone,
            student.father_email,
            student.father_occupation,
            parent_index,
            report,
        )
        if father_id:
            parents.append((father_id, FAMILY_ROLE_FATHER))

        mother_id = _resolve_parent(
            tenant_id,
            FAMILY_ROLE_MOTHER,
            student.mother_name,
            student.mother_phone,
            student.mother_email,
            student.mother_occupation,
            parent_index,
            report,
        )
        if mother_id:
            parents.append((mother_id, FAMILY_ROLE_MOTHER))

        # The admission form records a single guardian and how they are related,
        # which is how most students in v1 actually got their family details.
        guardian_role = family_role_for(student.guardian_relationship)
        guardian_id = _resolve_parent(
            tenant_id,
            guardian_role,
            student.guardian_name,
            student.guardian_phone,
            student.guardian_email,
            student.guardian_occupation,
            parent_index,
            report,
        )
        if guardian_id and guardian_id not in {person_id for person_id, _ in parents}:
            parents.append((guardian_id, guardian_role))

        if not parents:
            # A family with only a child records nothing worth keeping; it can
            # be created when parent details are entered.
            continue

        parent_ids = frozenset(person_id for person_id, _ in parents)
        family_id = families_by_parents.get(parent_ids)

        if family_id is None:
            family_id = _find_or_create_family(tenant_id, parents, report)
            families_by_parents[parent_ids] = family_id

        _add_membership(tenant_id, family_id, child_person_id, FAMILY_ROLE_CHILD, report)

    db.session.flush()
    return report


def _find_or_create_family(
    tenant_id: str, parents: List[Tuple[str, str]], report: BackfillReport
) -> str:
    """Reuse the family these parents already belong to, or start one."""
    parent_ids = [person_id for person_id, _ in parents]

    existing = (
        FamilyMember.query.filter(
            FamilyMember.tenant_id == tenant_id,
            FamilyMember.person_id.in_(parent_ids),
            # Any adult already in a family identifies that family; only a child
            # membership would point at the wrong household.
            FamilyMember.relationship != FAMILY_ROLE_CHILD,
        )
        .first()
    )
    if existing is not None:
        return existing.family_id

    family = Family(tenant_id=tenant_id)
    db.session.add(family)
    db.session.flush()
    report.families_created += 1

    for person_id, role in parents:
        _add_membership(tenant_id, family.id, person_id, role, report)

    return family.id


def _add_membership(
    tenant_id: str,
    family_id: str,
    person_id: str,
    relationship: str,
    report: BackfillReport,
) -> None:
    """Add a person to a family unless they are already in it."""
    exists = FamilyMember.query.filter(
        FamilyMember.tenant_id == tenant_id,
        FamilyMember.family_id == family_id,
        FamilyMember.person_id == person_id,
    ).first()
    if exists is not None:
        return

    db.session.add(
        FamilyMember(
            tenant_id=tenant_id,
            family_id=family_id,
            person_id=person_id,
            relationship=relationship,
        )
    )
    db.session.flush()
    report.memberships_created += 1
