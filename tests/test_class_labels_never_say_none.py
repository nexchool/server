"""A class label a person reads never says "None".

`name` is nullable and empty for every class the structured form creates — the
grade holds the label — so a caption built as `f"{name}-{section}"` renders
"None-A". A teacher opening the attendance picker in the mobile app saw exactly
that, on every class, in the demo school and any school onboarded the same way.

`Class.display_name` composes grade + section and falls back to the legacy name.
These pin the callers, not the property: the property was already right, and the
labels went on being built by hand beside it.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def graded_class(db_session, tenant):
    """A class as the structured form makes one: no name, a grade, a section."""
    from modules.academics.academic_year.models import AcademicYear
    from modules.classes.models import Class
    from modules.grades.models import Grade

    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    grade = Grade(id=_new_id("gr-"), tenant_id=tenant.id, name="1", sequence=1)
    db_session.add_all([year, grade])
    db_session.flush()
    cls = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name=None, section="A",
        grade_id=grade.id, academic_year_id=year.id,
    )
    db_session.add(cls)
    db_session.flush()
    return cls


def test_the_class_itself_composes_its_label(ctx, graded_class):
    assert graded_class.display_name == "1 A"


def test_the_shared_helper_does_not_build_its_own(ctx, graded_class):
    """`class_display_name` feeds the timetable and schedule captions."""
    from modules.academics.services.common import class_display_name

    label = class_display_name(graded_class)
    assert label == "1 A"
    assert "None" not in label


def test_a_class_with_only_a_section_is_labelled_by_its_section(
    ctx, db_session, tenant, graded_class
):
    """The thinnest class the schema permits.

    `classes.section` is NOT NULL, so a class always has at least that — there
    is no row for which `display_name` returns None. The callers still guard
    against it, which costs nothing and stops a future nullable column turning
    a caption into "None" or a sort into a TypeError.
    """
    from modules.academics.services.common import class_display_name
    from modules.classes.models import Class

    bare = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name=None, section="Z",
        academic_year_id=graded_class.academic_year_id,
    )
    db_session.add(bare)
    db_session.flush()

    assert class_display_name(bare) == "Z"


def test_the_attendance_picker_labels_a_class_by_its_grade(
    flask_app, db_session, tenant, graded_class
):
    """The screen the defect was found on.

    Also covers the sort: `display_name` can be None, and ordering that against
    strings raises, so a school with one unnamed class would 500 the picker.
    """
    from modules.attendance.session_services import get_eligible_classes_for_user
    from modules.auth.models import User
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Office",
    )
    db_session.add(user)
    db_session.flush()
    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Office-{suffix}")
    db_session.add(role)
    db_session.flush()
    permission = Permission.query.filter_by(name="attendance.manage").first()
    if permission is None:
        permission = Permission(id=_new_id("perm-"), name="attendance.manage")
        db_session.add(permission)
        db_session.flush()
    db_session.add(
        RolePermission(
            tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
        )
    )
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        result = get_eligible_classes_for_user(tenant.id, user.id, date(2026, 9, 1))

    assert result["success"]
    labels = [row["class_name"] for row in result["items"]]
    assert "1 A" in labels
    assert not any("None" in (label or "") for label in labels)
