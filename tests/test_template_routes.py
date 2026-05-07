"""Tests for template list/items and apply-subject-offerings endpoints.

Pure-Python, no Flask test client — uses monkeypatching in the same style as
tests/test_default_unit_endpoint.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


# ---------------------------------------------------------------------------
# Helper: unwrap decorators to call raw handler
# ---------------------------------------------------------------------------

def _unwrap(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


# ---------------------------------------------------------------------------
# list_templates
# ---------------------------------------------------------------------------

def test_list_templates_returns_groups(monkeypatch):
    """list_templates returns serialised groups from SubjectTemplateGroup.query."""
    from modules.school_setup import routes

    fake_group = MagicMock()
    fake_group.to_dict.return_value = {"id": "g1", "name": "CBSE", "board_code": "cbse", "is_active": True}

    fake_query = MagicMock()
    fake_query.filter_by.return_value = fake_query
    fake_query.order_by.return_value = fake_query
    fake_query.all.return_value = [fake_group]

    fake_stg = MagicMock()
    fake_stg.query = fake_query

    monkeypatch.setattr(routes, "SubjectTemplateGroup", fake_stg)

    success_calls = []

    def fake_success(data=None, message=None, **kw):
        success_calls.append(data)
        return ("ok", 200)

    monkeypatch.setattr(routes, "success_response", fake_success)

    handler = _unwrap(routes.list_templates)
    handler()

    assert len(success_calls) == 1
    assert success_calls[0][0]["name"] == "CBSE"


def test_list_templates_empty(monkeypatch):
    """list_templates with no active groups returns empty list."""
    from modules.school_setup import routes

    fake_query = MagicMock()
    fake_query.filter_by.return_value = fake_query
    fake_query.order_by.return_value = fake_query
    fake_query.all.return_value = []

    fake_stg = MagicMock()
    fake_stg.query = fake_query

    monkeypatch.setattr(routes, "SubjectTemplateGroup", fake_stg)

    success_calls = []

    def fake_success(data=None, message=None, **kw):
        success_calls.append(data)
        return ("ok", 200)

    monkeypatch.setattr(routes, "success_response", fake_success)

    handler = _unwrap(routes.list_templates)
    handler()

    assert success_calls[0] == []


# ---------------------------------------------------------------------------
# list_template_items
# ---------------------------------------------------------------------------

def test_list_template_items_200(monkeypatch):
    """list_template_items returns items when group exists."""
    from modules.school_setup import routes

    fake_group = MagicMock()
    fake_item = MagicMock()
    fake_item.to_dict.return_value = {
        "id": "i1",
        "template_group_id": "g1",
        "grade_number": 5,
        "subject_name": "Mathematics",
    }

    fake_group_query = MagicMock()
    fake_group_query.get.return_value = fake_group

    fake_item_query = MagicMock()
    fake_item_query.filter_by.return_value = fake_item_query
    fake_item_query.order_by.return_value = fake_item_query
    fake_item_query.all.return_value = [fake_item]

    fake_stg = MagicMock()
    fake_stg.query = fake_group_query

    fake_sti = MagicMock()
    fake_sti.query = fake_item_query

    monkeypatch.setattr(routes, "SubjectTemplateGroup", fake_stg)
    monkeypatch.setattr(routes, "SubjectTemplateItem", fake_sti)

    success_calls = []

    def fake_success(data=None, message=None, **kw):
        success_calls.append(data)
        return ("ok", 200)

    monkeypatch.setattr(routes, "success_response", fake_success)

    handler = _unwrap(routes.list_template_items)
    handler("g1")

    assert len(success_calls) == 1
    assert success_calls[0][0]["subject_name"] == "Mathematics"


def test_list_template_items_404_when_group_missing(monkeypatch):
    """list_template_items returns 404 when group_id not found."""
    from modules.school_setup import routes

    fake_group_query = MagicMock()
    fake_group_query.get.return_value = None

    fake_stg = MagicMock()
    fake_stg.query = fake_group_query

    monkeypatch.setattr(routes, "SubjectTemplateGroup", fake_stg)

    error_calls = []

    def fake_error(code, message, status, **kw):
        error_calls.append((code, status))
        return ("error", status)

    monkeypatch.setattr(routes, "error_response", fake_error)

    handler = _unwrap(routes.list_template_items)
    handler("ghost-group")

    assert error_calls and error_calls[0] == ("NotFound", 404)


# ---------------------------------------------------------------------------
# apply_subject_offerings_route
# ---------------------------------------------------------------------------

def test_apply_subject_offerings_route_400_when_no_year(monkeypatch):
    """Returns 400 when academic_year_id is missing from payload."""
    from modules.school_setup import routes

    fake_request = MagicMock()
    fake_request.get_json.return_value = {}

    monkeypatch.setattr(routes, "request", fake_request)

    error_calls = []

    def fake_error(code, message, status, **kw):
        error_calls.append((code, status))
        return ("error", status)

    monkeypatch.setattr(routes, "error_response", fake_error)

    handler = _unwrap(routes.apply_subject_offerings_route)
    result = handler()

    assert error_calls and error_calls[0] == ("ValidationError", 400)


def test_apply_subject_offerings_route_200_with_result(monkeypatch):
    """Returns 200 with created/skipped counts when academic_year_id is provided."""
    from modules.school_setup import routes

    fake_request = MagicMock()
    fake_request.get_json.return_value = {"academic_year_id": "ay-1"}

    fake_g = type("G", (), {"tenant_id": "t1"})()

    fake_service = MagicMock()
    fake_service.apply_subject_offerings.return_value = {"created": 10, "skipped": 2}

    monkeypatch.setattr(routes, "request", fake_request)
    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "apply_subjects_service", fake_service)

    success_calls = []

    def fake_success(data=None, message=None, **kw):
        success_calls.append(data)
        return ("ok", 200)

    monkeypatch.setattr(routes, "success_response", fake_success)

    handler = _unwrap(routes.apply_subject_offerings_route)
    handler()

    assert success_calls and success_calls[0] == {"created": 10, "skipped": 2}
    fake_service.apply_subject_offerings.assert_called_once_with(
        tenant_id="t1", academic_year_id="ay-1"
    )
