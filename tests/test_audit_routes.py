"""Tests for GET /api/audit-logs/ and GET /api/audit-logs/export endpoints.

Pure-Python, no Flask test client — uses monkeypatching in the same style as
tests/test_template_routes.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

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


def _make_row(**kwargs):
    """Build a minimal fake TenantAuditLog row."""
    defaults = {
        "id": "row-1",
        "created_at": datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
        "actor_user_id": "user-1",
        "actor_name": "Alice",
        "actor_role": "Admin",
        "module": "finance",
        "action": "create",
        "resource_type": "Invoice",
        "resource_id": "inv-1",
        "description": "Created invoice",
        "unit_id": "unit-1",
        "meta": None,
    }
    defaults.update(kwargs)
    row = MagicMock()
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


def _make_paginated_query(rows, total=None):
    """Build a fake query chain that returns *rows* from .all()."""
    if total is None:
        total = len(rows)
    q = MagicMock()
    q.filter_by.return_value = q
    q.filter.return_value = q
    q.count.return_value = total
    q.order_by.return_value = q
    q.offset.return_value = q
    q.limit.return_value = q
    q.all.return_value = rows
    return q


# ---------------------------------------------------------------------------
# list_audit_logs — basic return
# ---------------------------------------------------------------------------

def test_list_audit_logs_returns_rows(monkeypatch):
    """list_audit_logs returns serialised rows when query is mocked."""
    from modules.audit import routes

    row = _make_row()
    fake_query = _make_paginated_query([row])

    class FakeArgs(dict):
        def getlist(self, key):
            v = self.get(key)
            return [v] if v else []

    fake_request = MagicMock()
    fake_request.args = FakeArgs()

    fake_g = type("G", (), {"tenant_id": "t1"})()

    success_calls = []

    def fake_success(data=None, message=None, status_code=200, **kw):
        success_calls.append(data)
        return ("ok", 200)

    # Patch _build_query to avoid SQLAlchemy column comparison on MagicMock
    monkeypatch.setattr(routes, "_build_query", lambda tid, args: fake_query)
    monkeypatch.setattr(routes, "request", fake_request)
    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "success_response", fake_success)

    handler = _unwrap(routes.list_audit_logs)
    handler()

    assert len(success_calls) == 1
    items = success_calls[0]["items"]
    assert len(items) == 1
    assert items[0]["actor_name"] == "Alice"
    assert items[0]["module"] == "finance"


# ---------------------------------------------------------------------------
# list_audit_logs — pagination
# ---------------------------------------------------------------------------

def test_list_audit_logs_pagination(monkeypatch):
    """page=2, page_size=2 offsets by 2 and limits to 2."""
    from modules.audit import routes

    rows = [_make_row(id=f"row-{i}") for i in range(3, 5)]
    fake_query = _make_paginated_query(rows, total=10)

    class FakeArgs(dict):
        def getlist(self, key):
            v = self.get(key)
            return [v] if v else []

    fake_request = MagicMock()
    fake_request.args = FakeArgs({"page": "2", "page_size": "2"})

    fake_g = type("G", (), {"tenant_id": "t1"})()

    success_calls = []

    def fake_success(data=None, message=None, status_code=200, **kw):
        success_calls.append(data)
        return ("ok", 200)

    monkeypatch.setattr(routes, "_build_query", lambda tid, args: fake_query)
    monkeypatch.setattr(routes, "request", fake_request)
    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "success_response", fake_success)

    handler = _unwrap(routes.list_audit_logs)
    handler()

    # offset(2) and limit(2) must have been called
    fake_query.offset.assert_called_with(2)
    fake_query.limit.assert_called_with(2)

    pagination = success_calls[0]["pagination"]
    assert pagination["page"] == 2
    assert pagination["page_size"] == 2
    assert pagination["total_items"] == 10
    assert pagination["total_pages"] == 5


# ---------------------------------------------------------------------------
# _build_query — module filter
# ---------------------------------------------------------------------------

def test_build_query_applies_module_filter(monkeypatch):
    """_build_query calls query.filter when module is specified."""
    from modules.audit import routes

    filter_calls = []

    fake_q = MagicMock()
    fake_q.filter_by.return_value = fake_q

    def capturing_filter(*args, **kwargs):
        filter_calls.append(args)
        return fake_q

    fake_q.filter.side_effect = capturing_filter

    fake_col = MagicMock()
    # Make created_at >= expr return something truthy so the elif branch doesn't fire
    fake_col.__ge__ = lambda self, other: MagicMock()
    fake_col.in_ = lambda vals: MagicMock()

    fake_model = MagicMock()
    fake_model.query = fake_q
    fake_model.created_at = fake_col
    fake_model.module = fake_col
    fake_model.action = fake_col
    fake_model.actor_user_id = fake_col
    fake_model.unit_id = fake_col

    monkeypatch.setattr(routes, "TenantAuditLog", fake_model)

    class FakeArgs(dict):
        def getlist(self, key):
            v = self.get(key)
            return [v] if v else []

    # Provide date_from so the 30-day default branch is skipped, then add module
    args = FakeArgs({"date_from": "2026-01-01", "module": "finance"})
    routes._build_query("t1", args)

    # filter should have been called at least once (for date_from and for module)
    assert fake_q.filter.call_count >= 2


# ---------------------------------------------------------------------------
# _build_query — default last 30 days
# ---------------------------------------------------------------------------

def test_build_query_defaults_to_last_30_days(monkeypatch):
    """_build_query applies a 30-day lower bound when no date_from is given."""
    from modules.audit import routes

    filter_calls = []

    fake_q = MagicMock()
    fake_q.filter_by.return_value = fake_q

    def capturing_filter(*args, **kwargs):
        filter_calls.append(args)
        return fake_q

    fake_q.filter.side_effect = capturing_filter

    fake_col = MagicMock()
    fake_col.__ge__ = lambda self, other: MagicMock()

    fake_model = MagicMock()
    fake_model.query = fake_q
    fake_model.created_at = fake_col

    monkeypatch.setattr(routes, "TenantAuditLog", fake_model)

    class FakeArgs(dict):
        def getlist(self, key):
            return []

    args = FakeArgs()  # no date_from, no date_to
    routes._build_query("t1", args)

    # At least one filter call was made (the 30-day default)
    assert len(filter_calls) >= 1


# ---------------------------------------------------------------------------
# export_audit_logs — xlsx response
# ---------------------------------------------------------------------------

def test_export_audit_logs_returns_xlsx(monkeypatch):
    """export_audit_logs returns a response with xlsx mimetype and correct filename."""
    from modules.audit import routes

    row = _make_row()
    fake_query = _make_paginated_query([row])

    class FakeArgs(dict):
        def getlist(self, key):
            return []

    fake_request = MagicMock()
    fake_request.args = FakeArgs()

    fake_g = type("G", (), {"tenant_id": "t1"})()

    send_file_calls = []

    def fake_send_file(bio, mimetype=None, as_attachment=False, download_name=None):
        send_file_calls.append({
            "mimetype": mimetype,
            "as_attachment": as_attachment,
            "download_name": download_name,
        })
        return ("xlsx-response", 200)

    monkeypatch.setattr(routes, "_build_query", lambda tid, args: fake_query)
    monkeypatch.setattr(routes, "request", fake_request)
    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "send_file", fake_send_file)

    handler = _unwrap(routes.export_audit_logs)
    result = handler()

    assert len(send_file_calls) == 1
    call_info = send_file_calls[0]
    assert "spreadsheetml" in call_info["mimetype"]
    assert call_info["as_attachment"] is True
    assert call_info["download_name"] == "audit-log.xlsx"


# ---------------------------------------------------------------------------
# _exclusive_upper_bound — date_to must include the whole calendar day
# ---------------------------------------------------------------------------

def test_exclusive_upper_bound_date_only_advances_one_day():
    """A 'YYYY-MM-DD' end date becomes the NEXT day's midnight (exclusive), so
    entries recorded later on that same day are still included in the results."""
    from modules.audit import routes

    assert routes._exclusive_upper_bound("2026-06-10") == datetime(2026, 6, 11, 0, 0, 0)


def test_exclusive_upper_bound_timestamp_returns_none():
    """A full timestamp keeps the legacy inclusive (<=) behavior (returns None)."""
    from modules.audit import routes

    assert routes._exclusive_upper_bound("2026-06-10T15:30:00") is None


def test_exclusive_upper_bound_unparseable_returns_none():
    """Unparseable / missing values fall back to legacy behavior (None)."""
    from modules.audit import routes

    assert routes._exclusive_upper_bound("not-a-date") is None
    assert routes._exclusive_upper_bound(None) is None


def test_build_query_date_to_uses_exclusive_next_day(monkeypatch):
    """A date-only date_to filters with created_at < next-day-midnight."""
    from modules.audit import routes

    fake_q = MagicMock()
    fake_q.filter_by.return_value = fake_q
    fake_q.filter.return_value = fake_q

    fake_col = MagicMock()
    fake_col.__lt__ = lambda self, other: MagicMock()
    fake_col.__le__ = lambda self, other: MagicMock()

    fake_model = MagicMock()
    fake_model.query = fake_q
    fake_model.created_at = fake_col

    monkeypatch.setattr(routes, "TenantAuditLog", fake_model)

    bound_calls = []
    real_bound = routes._exclusive_upper_bound
    monkeypatch.setattr(
        routes,
        "_exclusive_upper_bound",
        lambda v: bound_calls.append(v) or real_bound(v),
    )

    class FakeArgs(dict):
        def getlist(self, key):
            return []

    routes._build_query("t1", FakeArgs({"date_to": "2026-06-10"}))

    assert bound_calls == ["2026-06-10"]
    fake_q.filter.assert_called()


def test_build_query_date_to_with_time_uses_inclusive(monkeypatch):
    """A full-timestamp date_to keeps the legacy <= bound (still filters)."""
    from modules.audit import routes

    fake_q = MagicMock()
    fake_q.filter_by.return_value = fake_q
    fake_q.filter.return_value = fake_q

    fake_col = MagicMock()
    fake_col.__lt__ = lambda self, other: MagicMock()
    fake_col.__le__ = lambda self, other: MagicMock()

    fake_model = MagicMock()
    fake_model.query = fake_q
    fake_model.created_at = fake_col

    monkeypatch.setattr(routes, "TenantAuditLog", fake_model)

    class FakeArgs(dict):
        def getlist(self, key):
            return []

    routes._build_query("t1", FakeArgs({"date_to": "2026-06-10T15:30:00"}))

    fake_q.filter.assert_called()
