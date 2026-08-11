"""The subject catalogue: `services.subjects_page`, `subjects_matching_count`
and `create_subject` with class_ids.

Exercised against PostgreSQL through the conftest savepoint harness, because
what is being tested is SQL filtering and paging.

The catalogue is read over GraphQL — `GET /api/subjects/` is deleted — so the
field itself, its guard and its enums are covered in
`test_academics_graphql.py`. What lives here is the service beneath both.
"""
from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _nid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}" if prefix else str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _make_academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_nid("ay-"),
        tenant_id=tenant.id,
        name=f"AY-{uuid.uuid4().hex[:4]}",
        start_date=date(2025, 6, 1),
        end_date=date(2026, 3, 31),
    )
    db_session.add(ay)
    db_session.flush()
    return ay


def _make_programme(db_session, tenant, *, name="GSEB Gujarati", code=None):
    from modules.academic_programmes.models import AcademicProgramme

    p = AcademicProgramme(
        id=_nid("prog-"),
        tenant_id=tenant.id,
        name=name,
        board="GSEB",
        code=code or f"PRG-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(p)
    db_session.flush()
    return p


def _make_grade(db_session, tenant, *, name="Grade 5", sequence=5):
    from modules.grades.models import Grade

    gr = Grade(id=_nid("g-"), tenant_id=tenant.id, name=name, sequence=sequence)
    db_session.add(gr)
    db_session.flush()
    return gr


def _make_class(db_session, tenant, ay, *, name=None, section="A",
                programme=None, grade=None):
    from modules.classes.models import Class

    c = Class(
        id=_nid("c-"),
        tenant_id=tenant.id,
        name=name,
        section=section,
        academic_year_id=ay.id,
        programme_id=programme.id if programme else None,
        grade_id=grade.id if grade else None,
    )
    db_session.add(c)
    db_session.flush()
    return c


def _make_subject(db_session, tenant, *, name, code=None, description=None,
                  subject_type="core", is_active=True):
    from modules.subjects.models import Subject

    s = Subject(
        id=_nid("subj-"),
        tenant_id=tenant.id,
        name=name,
        code=code,
        description=description,
        subject_type=subject_type,
        is_active=is_active,
    )
    db_session.add(s)
    db_session.flush()
    return s


def _make_class_subject(db_session, tenant, klass, subject, *, weekly_periods=5,
                        is_mandatory=True, status="active"):
    from modules.classes.models import ClassSubject

    cs = ClassSubject(
        id=_nid("cs-"),
        tenant_id=tenant.id,
        class_id=klass.id,
        subject_id=subject.id,
        weekly_periods=weekly_periods,
        is_mandatory=is_mandatory,
        status=status,
    )
    db_session.add(cs)
    db_session.flush()
    return cs


# ---------------------------------------------------------------------------
# subjects_page — paging
# ---------------------------------------------------------------------------

def test_a_page_starts_where_the_offset_says(db_session, tenant):
    from modules.subjects import services

    for i in range(25):
        _make_subject(db_session, tenant, name=f"Subject {i:02d}")

    items, has_more = services.subjects_page(tenant.id, first=10, offset=10)

    assert has_more is True
    assert [s["name"] for s in items] == [f"Subject {i:02d}" for i in range(10, 20)]
    assert services.subjects_matching_count(tenant.id) == 25


def test_the_last_page_says_there_is_no_more(db_session, tenant):
    from modules.subjects import services

    for i in range(25):
        _make_subject(db_session, tenant, name=f"Subject {i:02d}")

    items, has_more = services.subjects_page(tenant.id, first=10, offset=20)

    assert has_more is False
    assert len(items) == 5


def test_the_page_size_is_capped_by_the_service(db_session, tenant):
    """A cap a caller can route around is not a cap."""
    from modules.subjects import services

    for i in range(3):
        _make_subject(db_session, tenant, name=f"Subject {i}")

    items, _has_more = services.subjects_page(tenant.id, first=5000)
    assert len(items) == 3

    from modules.subjects.services import MAX_PER_PAGE

    assert MAX_PER_PAGE == 100


def test_a_catalogue_nothing_matches_is_empty(db_session, tenant):
    from modules.subjects import services

    items, has_more = services.subjects_page(tenant.id, search="nope")
    assert items == []
    assert has_more is False
    assert services.subjects_matching_count(tenant.id, search="nope") == 0


# ---------------------------------------------------------------------------
# subjects_page — search + filters
# ---------------------------------------------------------------------------

def test_search_matches_name_code_description_case_insensitive(db_session, tenant):
    from modules.subjects import services

    _make_subject(db_session, tenant, name="Mathematics", code="MATH")
    _make_subject(db_session, tenant, name="Science", code="SCI",
                  description="includes basic mathematics")
    _make_subject(db_session, tenant, name="History", code="HIST")

    found, _ = services.subjects_page(tenant.id, search="math")
    assert {s["name"] for s in found} == {"Mathematics", "Science"}

    by_code, _ = services.subjects_page(tenant.id, search="hist")
    assert [s["name"] for s in by_code] == ["History"]


def test_subject_type_filter(db_session, tenant):
    from modules.subjects import services

    _make_subject(db_session, tenant, name="Cricket", subject_type="activity")
    _make_subject(db_session, tenant, name="Maths", subject_type="core")

    found, _ = services.subjects_page(tenant.id, subject_type="activity")
    assert [s["name"] for s in found] == ["Cricket"]
    assert services.subjects_matching_count(tenant.id, subject_type="activity") == 1


def test_include_inactive_toggle(db_session, tenant):
    from modules.subjects import services

    _make_subject(db_session, tenant, name="Active One")
    _make_subject(db_session, tenant, name="Dormant", is_active=False)

    default, _ = services.subjects_page(tenant.id)
    assert {s["name"] for s in default} == {"Active One"}

    with_inactive, _ = services.subjects_page(tenant.id, include_inactive=True)
    assert {s["name"] for s in with_inactive} == {"Active One", "Dormant"}


def test_sort_by_code_desc(db_session, tenant):
    from modules.subjects import services

    _make_subject(db_session, tenant, name="A", code="AAA")
    _make_subject(db_session, tenant, name="B", code="ZZZ")

    found, _ = services.subjects_page(tenant.id, sort_by="code", sort_dir="desc")
    assert [s["code"] for s in found] == ["ZZZ", "AAA"]


def _make_other_tenant(db_session):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    t = Tenant(
        id=_nid("t-"),
        name="Other School",
        subdomain=f"other-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(t)
    db_session.flush()
    return t


def test_no_cross_tenant_leakage(db_session, tenant):
    from modules.subjects import services

    other = _make_other_tenant(db_session)
    _make_subject(db_session, tenant, name="Ours")
    _make_subject(db_session, other, name="Theirs")

    found, _ = services.subjects_page(tenant.id, search="")
    assert {s["name"] for s in found} == {"Ours"}
    assert services.subjects_matching_count(tenant.id) == 1


# ---------------------------------------------------------------------------
# subjects_page — classes[] / programmes[] enrichment
# ---------------------------------------------------------------------------

def test_items_carry_classes_and_programmes(db_session, tenant):
    from modules.subjects import services

    ay = _make_academic_year(db_session, tenant)
    prog = _make_programme(db_session, tenant, name="GSEB Gujarati")
    grade = _make_grade(db_session, tenant, name="Grade 5", sequence=5)
    klass = _make_class(db_session, tenant, ay, name="5-A", section="A",
                        programme=prog, grade=grade)
    subject = _make_subject(db_session, tenant, name="Maths", code="MATH")
    unassigned = _make_subject(db_session, tenant, name="Drawing")
    cs = _make_class_subject(db_session, tenant, klass, subject, weekly_periods=6)

    found, _ = services.subjects_page(tenant.id)
    by_name = {s["name"]: s for s in found}

    maths = by_name["Maths"]
    assert maths["classes"] == [
        {
            "class_subject_id": cs.id,
            "class_id": klass.id,
            # Named by its grade, from Class.display_name — not the "5-A"
            # free-text label, which is empty for every class the structured
            # form creates.
            "class_name": "Grade 5 A",
            "grade_name": "Grade 5",
            "programme_id": prog.id,
            "programme_name": "GSEB Gujarati",
            "weekly_periods": 6,
            "is_mandatory": True,
        }
    ]
    assert maths["programmes"] == [{"id": prog.id, "name": "GSEB Gujarati"}]
    assert by_name["Drawing"]["classes"] == []
    assert by_name["Drawing"]["programmes"] == []


def test_inactive_class_subject_rows_are_excluded(db_session, tenant):
    from modules.subjects import services

    ay = _make_academic_year(db_session, tenant)
    klass = _make_class(db_session, tenant, ay, section="B")
    subject = _make_subject(db_session, tenant, name="Maths")
    _make_class_subject(db_session, tenant, klass, subject, status="inactive")

    found, _ = services.subjects_page(tenant.id)
    assert found[0]["classes"] == []


# ---------------------------------------------------------------------------
# create_subject with class_ids
# ---------------------------------------------------------------------------

def test_create_with_class_ids_assigns_atomically(db_session, tenant):
    from modules.classes.models import ClassSubject
    from modules.subjects import services

    ay = _make_academic_year(db_session, tenant)
    k1 = _make_class(db_session, tenant, ay, section="A")
    k2 = _make_class(db_session, tenant, ay, section="B")

    result = services.create_subject(
        {
            "name": "Sanskrit",
            "code": "SANS",
            "class_ids": [k1.id, k2.id],
            "weekly_periods": 3,
        },
        tenant.id,
    )

    assert result["success"] is True
    assert result["assignment"] == {"created_count": 2, "skipped_count": 0}
    rows = ClassSubject.query.filter_by(
        tenant_id=tenant.id, subject_id=result["subject"]["id"]
    ).all()
    assert {r.class_id for r in rows} == {k1.id, k2.id}
    assert all(r.weekly_periods == 3 for r in rows)


def test_create_with_invalid_class_id_creates_nothing(db_session, tenant):
    from modules.subjects import services
    from modules.subjects.models import Subject

    result = services.create_subject(
        {"name": "Ghost", "class_ids": ["not-a-real-class"]}, tenant.id
    )

    assert result["success"] is False
    assert "class_id" in result["error"]
    assert (
        Subject.query.filter_by(tenant_id=tenant.id, name="Ghost").first() is None
    )


def test_create_with_bad_weekly_periods_creates_nothing(db_session, tenant):
    from modules.subjects import services
    from modules.subjects.models import Subject

    ay = _make_academic_year(db_session, tenant)
    klass = _make_class(db_session, tenant, ay, section="A")

    result = services.create_subject(
        {"name": "Ghost", "class_ids": [klass.id], "weekly_periods": 0}, tenant.id
    )

    assert result["success"] is False
    assert (
        Subject.query.filter_by(tenant_id=tenant.id, name="Ghost").first() is None
    )


def test_create_with_non_list_class_ids_rejected(db_session, tenant):
    from modules.subjects import services

    result = services.create_subject(
        {"name": "Bad", "class_ids": "abc"}, tenant.id
    )
    assert result["success"] is False
    assert "class_ids" in result["error"]


def test_create_with_real_board_types_persists(db_session, tenant):
    from modules.subjects import services

    for st in ("language", "co_curricular"):
        result = services.create_subject({"name": f"S-{st}", "subject_type": st}, tenant.id)
        assert result["success"] is True
        assert result["subject"]["subject_type"] == st


def test_create_with_unknown_subject_type_rejected(db_session, tenant):
    from modules.subjects import services

    result = services.create_subject(
        {"name": "Bad", "subject_type": "wizardry"}, tenant.id
    )
    assert result["success"] is False
    assert "subject_type" in result["error"]


def test_update_with_unknown_subject_type_rejected(db_session, tenant):
    from modules.subjects import services

    s = _make_subject(db_session, tenant, name="Maths")
    result = services.update_subject(s.id, {"subject_type": "wizardry"}, tenant.id)
    assert result["success"] is False
    assert "subject_type" in result["error"]


def test_create_duplicate_code_rejected(db_session, tenant):
    from modules.subjects import services

    _make_subject(db_session, tenant, name="Maths", code="MATH")
    result = services.create_subject({"name": "Maths 2", "code": "MATH"}, tenant.id)
    assert result["success"] is False
    assert "code" in result["error"].lower()


# ---------------------------------------------------------------------------
# Route: POST /api/subjects/ with class_ids requires class_subject.manage
# ---------------------------------------------------------------------------

def _run_create_handler(monkeypatch, body: dict, *, has_cs_manage: bool):
    import modules.rbac.services as rbac_services
    from modules.subjects import routes

    monkeypatch.setattr(
        rbac_services, "has_permission", lambda uid, perm: has_cs_manage
    )
    monkeypatch.setattr(
        routes,
        "g",
        type("G", (), {"tenant_id": "t1", "current_user": type("U", (), {"id": "u1"})()})(),
        raising=False,
    )
    monkeypatch.setattr(
        routes, "request", type("R", (), {"get_json": lambda self=None: body})()
    )

    captured = {}
    monkeypatch.setattr(
        routes,
        "error_response",
        lambda err, msg, status: captured.update(error=err, status=status) or ("err", status),
    )
    monkeypatch.setattr(
        routes,
        "success_response",
        lambda **kw: captured.update(success=True) or ("ok", kw.get("status_code", 200)),
    )
    monkeypatch.setattr(
        routes.services,
        "create_subject",
        lambda data, tid: {"success": True, "subject": {"id": "s1"}},
    )

    handler = routes.create_subject
    while hasattr(handler, "__wrapped__"):
        handler = handler.__wrapped__
    response = handler()
    return response, captured


def test_route_create_with_class_ids_requires_class_subject_manage(monkeypatch):
    response, captured = _run_create_handler(
        monkeypatch,
        {"name": "Maths", "class_ids": ["c1"]},
        has_cs_manage=False,
    )
    assert response[1] == 403
    assert captured["error"] == "AuthorizationError"


def test_route_create_with_class_ids_allowed_with_permission(monkeypatch):
    response, captured = _run_create_handler(
        monkeypatch,
        {"name": "Maths", "class_ids": ["c1"]},
        has_cs_manage=True,
    )
    assert captured.get("success") is True


def test_route_create_without_class_ids_skips_permission_check(monkeypatch):
    # has_cs_manage=False must not matter when no class_ids are sent.
    response, captured = _run_create_handler(
        monkeypatch, {"name": "Maths"}, has_cs_manage=False
    )
    assert captured.get("success") is True



# ---------------------------------------------------------------------------
# The one REST read the Expo client still needs
# ---------------------------------------------------------------------------

def test_the_mobile_subject_list_still_answers(flask_app, db_session, tenant):
    """`GET /api/subjects/` is `subjectService.getSubjects` on mobile.

    The administrator's paginated catalogue that used to hide behind this
    URL's query params is gone — admin-web reads `subjectCatalogue` on
    GraphQL. The flat array stays until the Expo release that moves the app,
    and reads `list_subjects_filtered`, the same function GraphQL's `subjects`
    field calls, so there is one reader.
    """
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from modules.auth.models import User
    from tests.conftest import grant_profile_to

    _make_subject(db_session, tenant, name="Mathematics", code="MATH")
    _make_subject(db_session, tenant, name="Retired", is_active=False)

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Staff",
    )
    db_session.add(user)
    db_session.flush()
    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Role-{suffix}")
    db_session.add(role)
    db_session.flush()
    permission = Permission.query.filter_by(name="subject.read").first()
    if permission is None:
        permission = Permission(id=_nid("perm-"), name="subject.read")
        db_session.add(permission)
        db_session.flush()
    db_session.add(
        RolePermission(
            tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
        )
    )
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")

    response = flask_app.test_client().get(
        "/api/subjects/",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {generate_access_token(user)}",
        },
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()["data"]
    assert isinstance(payload, list), "the mobile app reads a flat array"
    assert [s["name"] for s in payload] == ["Mathematics"]
