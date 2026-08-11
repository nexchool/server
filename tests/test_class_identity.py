"""What makes two sections the same section.

A class is identified by where it sits — campus, programme, grade, section
letter, academic year — not by what it is called. `name` is a nullable legacy
label and is empty for every class created through the structured form, so a
duplicate check that reads it collapses to (section, year) and refuses the
second Grade 1 A a school opens on another programme.

That is not a hypothetical: the demo school has Grade 1 A twice, once GSEB
Gujarati and once GSEB English, on one campus. The seeder built them, because
`create_class` would have refused the second.
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
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    db_session.add(year)
    db_session.flush()
    return year


@pytest.fixture
def structure(db_session, tenant):
    """One campus, two programmes on it, one grade — the demo school's shape."""
    from modules.academic_programmes.models import AcademicProgramme
    from modules.grades.models import Grade
    from modules.school_units.models import SchoolUnit

    suffix = uuid.uuid4().hex[:6]
    campus = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="Main Campus",
        code=f"MC-{suffix}",
    )
    other_campus = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="North Campus",
        code=f"NC-{suffix}",
    )
    gujarati = AcademicProgramme(
        id=_new_id("pr-"), tenant_id=tenant.id, name="GSEB Gujarati Medium",
        board="GSEB", medium="Gujarati", code=f"GG-{suffix}",
    )
    english = AcademicProgramme(
        id=_new_id("pr-"), tenant_id=tenant.id, name="GSEB English Medium",
        board="GSEB", medium="English", code=f"GE-{suffix}",
    )
    grade = Grade(id=_new_id("gr-"), tenant_id=tenant.id, name="1", sequence=1)
    db_session.add_all([campus, other_campus, gujarati, english, grade])
    db_session.flush()
    return {
        "campus": campus,
        "other_campus": other_campus,
        "gujarati": gujarati,
        "english": english,
        "grade": grade,
    }


def _create(academic_year, structure, *, section="A", programme=None, campus=None):
    from modules.classes.services import create_class

    return create_class(
        name="",
        section=section,
        academic_year_id=academic_year.id,
        grade_id=structure["grade"].id,
        programme_id=(programme or structure["gujarati"]).id,
        school_unit_id=(campus or structure["campus"]).id,
    )


def test_the_same_section_letter_on_two_programmes_is_two_sections(
    ctx, academic_year, structure
):
    """The case the demo school already has, and the old check refused."""
    first = _create(academic_year, structure, programme=structure["gujarati"])
    assert first["success"], first

    second = _create(academic_year, structure, programme=structure["english"])
    assert second["success"], second
    assert second["class"]["id"] != first["class"]["id"]


def test_the_same_section_letter_on_two_campuses_is_two_sections(
    ctx, academic_year, structure
):
    """A trust runs Grade 1 A at every campus it teaches Grade 1 at."""
    first = _create(academic_year, structure, campus=structure["campus"])
    assert first["success"], first

    second = _create(academic_year, structure, campus=structure["other_campus"])
    assert second["success"], second


def test_the_same_section_in_the_same_place_is_refused(
    ctx, academic_year, structure
):
    """The check still has to do its job."""
    assert _create(academic_year, structure)["success"]

    again = _create(academic_year, structure)
    assert not again["success"]
    assert "already exists" in again["error"]


def test_a_different_section_letter_in_the_same_place_is_allowed(
    ctx, academic_year, structure
):
    assert _create(academic_year, structure, section="A")["success"]
    assert _create(academic_year, structure, section="B")["success"]


def test_naming_a_section_differently_does_not_make_it_a_new_one(
    ctx, academic_year, structure
):
    """The defect in reverse.

    Identity is where a section sits. Two rows for Grade 1 A on one programme
    are the same section however they are labelled — which the old check, keyed
    on `name`, would have waved through as two.
    """
    from modules.classes.services import create_class

    first = create_class(
        name="Grade 1 A",
        section="A",
        academic_year_id=academic_year.id,
        grade_id=structure["grade"].id,
        programme_id=structure["gujarati"].id,
        school_unit_id=structure["campus"].id,
    )
    assert first["success"], first

    second = create_class(
        name="Std 1 A",  # same section, different label
        section="A",
        academic_year_id=academic_year.id,
        grade_id=structure["grade"].id,
        programme_id=structure["gujarati"].id,
        school_unit_id=structure["campus"].id,
    )
    assert not second["success"]


# ---------------------------------------------------------------------------
# What a section has to be called
# ---------------------------------------------------------------------------

def _post(client, tenant, token, payload):
    return client.post(
        "/api/classes/",
        json=payload,
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {token}",
        },
    )


@pytest.fixture
def registrar(db_session, tenant):
    """Somebody who may open a section, and a school that has finished setup."""
    import uuid as _uuid

    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    tenant.is_setup_complete = True
    suffix = _uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Registrar",
    )
    db_session.add(user)
    db_session.flush()
    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Office-{suffix}")
    db_session.add(role)
    db_session.flush()
    for key in ("class.create", "class.read"):
        permission = Permission.query.filter_by(name=key).first()
        if permission is None:
            permission = Permission(id=_new_id("perm-"), name=key)
            db_session.add(permission)
            db_session.flush()
        db_session.add(
            RolePermission(
                tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
            )
        )
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")
    return user, generate_access_token(user)


def test_a_section_with_a_grade_needs_no_name(
    flask_app, db_session, tenant, academic_year, structure, registrar
):
    """The defect that left admin-web unable to open a section at all.

    The route demanded a name unless `grade_level` — the older integer form —
    was set. The structured form sends `grade_id`, so every section it tried to
    create was refused, and the label is composed from the grade anyway.
    """
    _user, token = registrar
    response = _post(
        flask_app.test_client(), tenant, token,
        {
            "name": "",
            "section": "C",
            "academic_year_id": academic_year.id,
            "school_unit_id": structure["campus"].id,
            "programme_id": structure["gujarati"].id,
            "grade_id": structure["grade"].id,
        },
    )
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["data"]["display_name"] == "1 C"


def test_a_section_with_no_grade_at_all_still_needs_a_name(
    flask_app, db_session, tenant, academic_year, registrar
):
    """The rule is not removed, only narrowed — with no grade there is no label."""
    _user, token = registrar
    response = _post(
        flask_app.test_client(), tenant, token,
        {"name": "", "section": "D", "academic_year_id": academic_year.id},
    )
    assert response.status_code == 400
    assert "name is required" in str(response.get_json())
