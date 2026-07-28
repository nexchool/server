"""Bulk teacher import resolves department names against the catalogue."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


@pytest.fixture
def dept_svc():
    from modules.departments import services

    return services


@pytest.fixture
def importer():
    from modules.teachers import bulk_teacher_import_service

    return bulk_teacher_import_service


def test_known_department_name_resolves_to_the_id(db_session, tenant, dept_svc):
    dept = dept_svc.create_department({"name": "Science"}, tenant.id)["department"]

    assert dept_svc.resolve_department_name("science", tenant.id) == dept["id"]
    assert dept_svc.resolve_department_name("  SCIENCE  ", tenant.id) == dept["id"]


def test_unknown_department_name_resolves_to_none(db_session, tenant, dept_svc):
    assert dept_svc.resolve_department_name("Nope", tenant.id) is None


def test_import_row_with_an_unknown_department_is_rejected(db_session, tenant, dept_svc, importer):
    """One bad row must not abort the whole file."""
    dept_svc.create_department({"name": "Science"}, tenant.id)

    rows = [
        {"name": "Good Teacher", "email": "good@example.test", "department": "Science"},
        {"name": "Bad Teacher", "email": "bad@example.test", "department": "Nonexistent"},
    ]
    row_numbers = [2, 3]

    result = importer.import_teachers_from_rows(
        rows, row_numbers, tenant_id=tenant.id, send_email=False
    )

    assert result["success"] == 1
    assert result["failed"] == 1
    failed = result["failed_rows"]
    assert len(failed) == 1
    assert failed[0]["row_number"] == 3
    assert any("Nonexistent" in msg for msg in failed[0]["errors"])


def test_import_row_with_a_known_department_persists_department_id(
    db_session, tenant, dept_svc, importer
):
    from modules.teachers.models import Teacher

    dept = dept_svc.create_department({"name": "Mathematics"}, tenant.id)["department"]

    rows = [
        {
            "name": "Good Teacher",
            "email": "good-math@example.test",
            "department": "  mathematics  ",
        }
    ]

    result = importer.import_teachers_from_rows(
        rows, [2], tenant_id=tenant.id, send_email=False
    )

    assert result["success"] == 1
    assert result["failed"] == 0

    teacher = Teacher.query.filter_by(tenant_id=tenant.id).one()
    assert teacher.department_id == dept["id"]


def test_blank_department_is_not_an_error(db_session, tenant, importer):
    rows = [
        {"name": "No Dept Teacher", "email": "no-dept@example.test", "department": ""},
    ]

    result = importer.import_teachers_from_rows(
        rows, [2], tenant_id=tenant.id, send_email=False
    )

    assert result["success"] == 1
    assert result["failed"] == 0


def test_department_names_are_resolved_once_per_distinct_value(
    db_session, tenant, dept_svc, importer, monkeypatch
):
    """Repeating the same department across many rows must not re-query per row."""
    from modules.departments import services as dept_services

    dept_svc.create_department({"name": "Science"}, tenant.id)

    calls = []
    original = dept_services.resolve_department_name

    def counting_resolve(name, tid):
        calls.append(name)
        return original(name, tid)

    monkeypatch.setattr(dept_services, "resolve_department_name", counting_resolve)

    rows = [
        {"name": f"Teacher {i}", "email": f"teacher{i}@example.test", "department": "Science"}
        for i in range(5)
    ]
    row_numbers = list(range(2, 7))

    result = importer.import_teachers_from_rows(
        rows, row_numbers, tenant_id=tenant.id, send_email=False
    )

    assert result["success"] == 5
    assert len(calls) == 1
