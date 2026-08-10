"""A second campus, and somebody who may only see it.

The product promises 1 → 20+ campuses per tenant, and every tenant-scoped
domain is meant to be branch-aware. The demo school has **one** campus and no
restricted user, so none of that can be exercised by using the app — branch
scope is covered by tests and by nothing a person can click.

This adds the smallest fixture that makes it real:

  - a second campus, North Campus
  - Grade 1 A and 1 B on it, which also exercises the same section letter
    existing on two campuses (see `test_class_identity.py`)
  - a sub-admin restricted to North Campus, holding Classes and Students

Idempotent: re-running finds what it made and leaves it alone.

    python -m scripts.seed_multi_campus_fixture --tenant default
    python -m scripts.seed_multi_campus_fixture --tenant default --remove
"""

from __future__ import annotations

import argparse
import sys
import uuid

from app import create_app
from core.database import db
from core.models import Tenant

CAMPUS_NAME = "North Campus"
CAMPUS_CODE = "NORTH"
SUBADMIN_EMAIL = "north.head@nexchool.in"
SUBADMIN_PASSWORD = "Branch@123"
SECTIONS = ("A", "B")


def _tenant(subdomain: str) -> Tenant:
    tenant = Tenant.query.filter_by(subdomain=subdomain).first()
    if tenant is None:
        raise SystemExit(f"No tenant with subdomain {subdomain!r}")
    return tenant


def _campus(tenant_id: str):
    from modules.school_units.models import SchoolUnit

    return SchoolUnit.query.filter_by(tenant_id=tenant_id, code=CAMPUS_CODE).first()


def _teach_the_same_subjects(
    tenant_id: str, campus_id: str, grade_id: str, programme_id: str, year_id: str
) -> None:
    """Give the new sections the subjects their counterpart already teaches.

    Not decoration. `school_setup` counts a class with no subjects as a blocker,
    and one unresolved blocker leaves the whole tenant setup-incomplete — which
    puts every admin screen behind "School setup is incomplete". A fixture that
    opens a campus and stops has therefore been locking the local app out of
    itself; a real school opening a branch does not leave its classes teaching
    nothing.

    The source is the same grade and programme on another campus, so the two
    branches teach alike, which is also what makes the branch-scope tests this
    fixture exists for meaningful.
    """
    from modules.classes.models import Class, ClassSubject

    template = (
        Class.query.filter(
            Class.tenant_id == tenant_id,
            Class.grade_id == grade_id,
            Class.programme_id == programme_id,
            Class.school_unit_id != campus_id,
        )
        .order_by(Class.section)
        .first()
    )
    if template is None:
        print("  ! no counterpart class to copy subjects from — left empty")
        return

    lessons = ClassSubject.query.filter_by(
        tenant_id=tenant_id, class_id=template.id, deleted_at=None
    ).all()
    if not lessons:
        print("  ! the counterpart class teaches nothing — left empty")
        return

    for new_class in Class.query.filter_by(
        tenant_id=tenant_id, school_unit_id=campus_id, academic_year_id=year_id
    ).all():
        if ClassSubject.query.filter_by(
            tenant_id=tenant_id, class_id=new_class.id
        ).first():
            continue
        for lesson in lessons:
            db.session.add(
                ClassSubject(
                    id=f"cs-{uuid.uuid4().hex[:12]}",
                    tenant_id=tenant_id,
                    class_id=new_class.id,
                    subject_id=lesson.subject_id,
                    weekly_periods=lesson.weekly_periods,
                    is_mandatory=lesson.is_mandatory,
                    is_elective_bucket=lesson.is_elective_bucket,
                    sort_order=lesson.sort_order,
                )
            )
        print(f"  + {len(lessons)} subject(s) for section {new_class.section}")
    db.session.commit()


def add(tenant: Tenant) -> None:
    from flask import g

    from modules.academic_programmes.models import AcademicProgramme
    from modules.academics.academic_year.models import AcademicYear
    from modules.classes.models import Class
    from modules.grades.models import Grade
    from modules.school_units.models import SchoolUnit
    from modules.sub_admins.services import create_sub_admin

    g.tenant_id = tenant.id

    campus = _campus(tenant.id)
    if campus is None:
        campus = SchoolUnit(
            id=f"su-{uuid.uuid4().hex[:12]}",
            tenant_id=tenant.id,
            name=CAMPUS_NAME,
            code=CAMPUS_CODE,
        )
        db.session.add(campus)
        db.session.commit()
        print(f"  + campus {CAMPUS_NAME}")
    else:
        print(f"  = campus {CAMPUS_NAME} already there")

    year = AcademicYear.query.filter_by(tenant_id=tenant.id, is_active=True).first()
    grade = (
        Grade.query.filter_by(tenant_id=tenant.id)
        .order_by(Grade.sequence)
        .first()
    )
    programme = AcademicProgramme.query.filter_by(tenant_id=tenant.id).first()
    if not (year and grade and programme):
        raise SystemExit("Tenant has no active year / grade / programme to build on.")

    for section in SECTIONS:
        existing = Class.query.filter_by(
            tenant_id=tenant.id,
            school_unit_id=campus.id,
            programme_id=programme.id,
            grade_id=grade.id,
            section=section,
            academic_year_id=year.id,
        ).first()
        if existing:
            print(f"  = {grade.name} {section} already on {CAMPUS_NAME}")
            continue
        db.session.add(
            Class(
                id=f"c-{uuid.uuid4().hex[:12]}",
                tenant_id=tenant.id,
                name="",
                section=section,
                academic_year_id=year.id,
                school_unit_id=campus.id,
                programme_id=programme.id,
                grade_id=grade.id,
            )
        )
        print(f"  + {grade.name} {section} on {CAMPUS_NAME}")
    db.session.commit()

    _teach_the_same_subjects(tenant.id, campus.id, grade.id, programme.id, year.id)

    from modules.auth.models import User
    from modules.sub_admins.services import update_sub_admin

    selection = [
        {"key": "classes", "level": "manage", "toggles": {}},
        {"key": "students", "level": "edit", "toggles": {}},
    ]

    existing = User.query.filter_by(tenant_id=tenant.id, email=SUBADMIN_EMAIL).first()
    if existing:
        # Re-sync rather than skip. The permissions a module grants come from
        # the catalogue, and the catalogue changes — a fixture that skips an
        # existing user hands you yesterday's grants and looks idempotent while
        # testing the wrong thing.
        result = update_sub_admin(
            tenant_id=tenant.id,
            user_id=existing.id,
            modules=selection,
            branch_unit_ids=[campus.id],
        )
        if not result.get("success"):
            raise SystemExit(f"Could not re-sync the sub-admin: {result}")
        print(f"  = sub-admin {SUBADMIN_EMAIL} re-synced from the catalogue")
        return

    # Through the real service, not raw rows: it is what creates the private
    # role, the UserSchoolUnit restriction and the permission grants together,
    # and it refuses a branch restriction on a module that is not branch-aware.
    result = create_sub_admin(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        name="North Campus Head",
        email=SUBADMIN_EMAIL,
        password=SUBADMIN_PASSWORD,
        modules=selection,
        branch_unit_ids=[campus.id],
    )
    if not result.get("success"):
        raise SystemExit(f"Could not create the sub-admin: {result}")
    print(f"  + sub-admin {SUBADMIN_EMAIL} / {SUBADMIN_PASSWORD}, {CAMPUS_NAME} only")


def remove(tenant: Tenant) -> None:
    from modules.auth.models import User
    from modules.classes.models import Class

    campus = _campus(tenant.id)
    if campus is None:
        print("  = nothing to remove")
        return

    removed = Class.query.filter_by(
        tenant_id=tenant.id, school_unit_id=campus.id
    ).delete(synchronize_session=False)
    print(f"  - {removed} section(s) on {CAMPUS_NAME}")

    user = User.query.filter_by(tenant_id=tenant.id, email=SUBADMIN_EMAIL).first()
    if user:
        # Hard delete, not `delete_sub_admin`. That soft-deletes, which leaves
        # the email taken — so a later `--add` finds the tombstone and the
        # fixture stops being reversible. (It also refuses outright when the
        # actor is the user being deleted, which is what made an earlier
        # version of this a silent no-op.)
        from modules.rbac.models import Role, RolePermission, StaffAuthority
        from modules.sub_admins.models import UserSchoolUnit

        role = Role.query.filter_by(
            tenant_id=tenant.id, name=f"subadmin:{user.id}"
        ).first()
        if role:
            StaffAuthority.query.filter_by(role_id=role.id).delete(
                synchronize_session=False
            )
            RolePermission.query.filter_by(role_id=role.id).delete(
                synchronize_session=False
            )
        UserSchoolUnit.query.filter_by(user_id=user.id).delete(
            synchronize_session=False
        )
        db.session.flush()
        if role:
            db.session.delete(role)
        db.session.delete(user)
        db.session.commit()
        print(f"  - sub-admin {SUBADMIN_EMAIL}")

    db.session.delete(campus)
    db.session.commit()
    print(f"  - campus {CAMPUS_NAME}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="default", help="Tenant subdomain.")
    parser.add_argument("--remove", action="store_true", help="Take the fixture out.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        tenant = _tenant(args.tenant)
        print(f"{'Removing from' if args.remove else 'Adding to'} {tenant.subdomain}:")
        (remove if args.remove else add)(tenant)
    return 0


if __name__ == "__main__":
    sys.exit(main())
