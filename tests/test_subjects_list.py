"""Tests for the paginated subject catalogue: services.list_subjects_paginated,
create_subject with class_ids, and the GET /api/subjects/ envelope switch.

Service tests use the real-DB savepoint harness (conftest `db_session`,
`tenant`) — the logic is SQL filtering/pagination, which we want to exercise
against PostgreSQL. Route tests are pure-Python (unwrap decorators, mock the
service) following test_subjects_mine.py.
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
# list_subjects_paginated — pagination
# ---------------------------------------------------------------------------

def test_pagination_envelope_and_page_slicing(db_session, tenant):
    from modules.subjects import services

    for i in range(25):
        _make_subject(db_session, tenant, name=f"Subject {i:02d}")

    result = services.list_subjects_paginated(tenant.id, page=2, per_page=10)

    assert result["total"] == 25
    assert result["page"] == 2
    assert result["per_page"] == 10
    assert result["total_pages"] == 3
    assert [s["name"] for s in result["items"]] == [
        f"Subject {i:02d}" for i in range(10, 20)
    ]


def test_per_page_is_capped_at_100(db_session, tenant):
    from modules.subjects import services

    _make_subject(db_session, tenant, name="Solo")
    result = services.list_subjects_paginated(tenant.id, per_page=5000)
    assert result["per_page"] == 100


def test_empty_result_has_zero_total_pages(db_session, tenant):
    from modules.subjects import services

    result = services.list_subjects_paginated(tenant.id, search="nope")
    assert result["items"] == []
    assert result["total"] == 0
    assert result["total_pages"] == 0


# ---------------------------------------------------------------------------
# list_subjects_paginated — search + filters
# ---------------------------------------------------------------------------

def test_search_matches_name_code_description_case_insensitive(db_session, tenant):
    from modules.subjects import services

    _make_subject(db_session, tenant, name="Mathematics", code="MATH")
    _make_subject(db_session, tenant, name="Science", code="SCI",
                  description="includes basic mathematics")
    _make_subject(db_session, tenant, name="History", code="HIST")

    result = services.list_subjects_paginated(tenant.id, search="math")
    assert {s["name"] for s in result["items"]} == {"Mathematics", "Science"}

    by_code = services.list_subjects_paginated(tenant.id, search="hist")
    assert [s["name"] for s in by_code["items"]] == ["History"]


def test_subject_type_filter(db_session, tenant):
    from modules.subjects import services

    _make_subject(db_session, tenant, name="Cricket", subject_type="activity")
    _make_subject(db_session, tenant, name="Maths", subject_type="core")

    result = services.list_subjects_paginated(tenant.id, subject_type="activity")
    assert [s["name"] for s in result["items"]] == ["Cricket"]


def test_include_inactive_toggle(db_session, tenant):
    from modules.subjects import services

    _make_subject(db_session, tenant, name="Active One")
    _make_subject(db_session, tenant, name="Dormant", is_active=False)

    default = services.list_subjects_paginated(tenant.id)
    assert {s["name"] for s in default["items"]} == {"Active One"}

    with_inactive = services.list_subjects_paginated(tenant.id, include_inactive=True)
    assert {s["name"] for s in with_inactive["items"]} == {"Active One", "Dormant"}


def test_sort_by_code_desc(db_session, tenant):
    from modules.subjects import services

    _make_subject(db_session, tenant, name="A", code="AAA")
    _make_subject(db_session, tenant, name="B", code="ZZZ")

    result = services.list_subjects_paginated(tenant.id, sort_by="code", sort_dir="desc")
    assert [s["code"] for s in result["items"]] == ["ZZZ", "AAA"]


def _make_other_tenant(db_session):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    t = Tenant(
        id=_nid("t-"),
        name="Other School",
        subdomain=f"other-{uuid.uuid4().hex[:6]}",
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

    result = services.list_subjects_paginated(tenant.id, search="")
    assert {s["name"] for s in result["items"]} == {"Ours"}


# ---------------------------------------------------------------------------
# list_subjects_paginated — classes[] / programmes[] enrichment
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

    result = services.list_subjects_paginated(tenant.id)
    by_name = {s["name"]: s for s in result["items"]}

    maths = by_name["Maths"]
    assert maths["classes"] == [
        {
            "class_subject_id": cs.id,
            "class_id": klass.id,
            "class_name": "5-A",
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

    result = services.list_subjects_paginated(tenant.id)
    assert result["items"][0]["classes"] == []


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
# Route: GET /api/subjects/ envelope switch + param validation (pure-Python)
# ---------------------------------------------------------------------------

class _FakeArgs(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def _run_list_handler(monkeypatch, args: dict):
    from modules.subjects import routes

    monkeypatch.setattr(
        routes, "g", type("G", (), {"tenant_id": "t1"})(), raising=False
    )
    monkeypatch.setattr(
        routes, "request", type("R", (), {"args": _FakeArgs(args)})()
    )

    captured = {}
    monkeypatch.setattr(
        routes,
        "success_response",
        lambda data=None, **kw: captured.__setitem__("data", data) or ("ok", 200),
    )
    monkeypatch.setattr(
        routes,
        "validation_error_response",
        lambda msg, **kw: captured.__setitem__("error", msg) or ("bad", 400),
    )

    handler = routes.list_subjects
    while hasattr(handler, "__wrapped__"):
        handler = handler.__wrapped__
    response = handler()
    return response, captured


def test_route_without_list_params_returns_legacy_array(monkeypatch):
    from modules.subjects import routes

    legacy = [{"id": "s1", "name": "Maths"}]
    monkeypatch.setattr(
        routes.services, "get_subjects", lambda tid, include_inactive=False: legacy
    )
    response, captured = _run_list_handler(monkeypatch, {})
    assert response == ("ok", 200)
    assert captured["data"] == legacy


def test_route_with_page_param_returns_envelope(monkeypatch):
    from modules.subjects import routes

    envelope = {"items": [], "total": 0, "page": 1, "per_page": 20, "total_pages": 0}
    monkeypatch.setattr(
        routes.services, "list_subjects_paginated", lambda tid, **kw: envelope
    )
    response, captured = _run_list_handler(monkeypatch, {"page": "1"})
    assert response == ("ok", 200)
    assert captured["data"] == envelope


def test_route_rejects_non_integer_page(monkeypatch):
    response, captured = _run_list_handler(monkeypatch, {"page": "abc"})
    assert response == ("bad", 400)
    assert "page" in captured["error"]


def test_route_rejects_bad_sort_by(monkeypatch):
    response, captured = _run_list_handler(monkeypatch, {"sort_by": "evil"})
    assert response == ("bad", 400)
    assert "sort_by" in captured["error"]


def test_route_rejects_bad_subject_type(monkeypatch):
    response, captured = _run_list_handler(monkeypatch, {"subject_type": "wizardry"})
    assert response == ("bad", 400)
    assert "subject_type" in captured["error"]
