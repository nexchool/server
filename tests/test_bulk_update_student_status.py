"""Tests for services.bulk_update_status (bulk student status change)."""

from flask import g


def _call_bulk(flask_app, tenant, student_ids, status):
    from modules.students import services

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        return services.bulk_update_status(student_ids, status)


def test_bulk_update_sets_status_for_all_selected(flask_app, db_session, tenant, student, student2):
    from modules.students.models import Student

    result = _call_bulk(flask_app, tenant, [student.id, student2.id], "graduated")

    assert result["success"] is True
    assert result["updated"] == 2
    assert result["missing"] == []
    assert Student.query.get(student.id).student_status == "graduated"
    assert Student.query.get(student2.id).student_status == "graduated"


def test_bulk_update_reports_missing_ids(flask_app, db_session, tenant, student):
    result = _call_bulk(flask_app, tenant, [student.id, "does-not-exist"], "inactive")

    assert result["success"] is True
    assert result["updated"] == 1
    assert result["missing"] == ["does-not-exist"]


def test_bulk_update_rejects_invalid_status(flask_app, db_session, tenant, student):
    result = _call_bulk(flask_app, tenant, [student.id], "not-a-real-status")

    assert result["success"] is False
    assert "Invalid status" in result["error"]


def test_bulk_update_rejects_empty_selection(flask_app, db_session, tenant):
    result = _call_bulk(flask_app, tenant, [], "active")

    assert result["success"] is False
