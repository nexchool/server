"""Finance ↔ transport cross-feature gating: transport-only fee structures
must be invisible to finance listings when the transport feature is off.

This locks in the data contract: existing transport rows are preserved, but
finance UI/API never surfaces them while transport is disabled.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import core.feature_flags as ff_mod
import modules.finance.services.structure_service as structure_service
import modules.finance.services.student_fee_service as student_fee_service


def test_list_fee_structures_excludes_transport_only_when_transport_off(monkeypatch):
    monkeypatch.setattr(ff_mod, "is_feature_enabled", lambda _t, k: k != "transport")
    monkeypatch.setattr(structure_service, "get_tenant_id", lambda: "tenant-1")

    captured: dict = {}

    fake_query = MagicMock()
    fake_query.filter_by.return_value = fake_query
    fake_query.order_by.return_value = fake_query
    fake_query.all.return_value = []

    def _filter(*args, **kwargs):
        captured["filter_called"] = True
        captured["filter_args"] = args
        return fake_query

    fake_query.filter.side_effect = _filter

    fake_model = MagicMock()
    fake_model.query = fake_query
    fake_model.is_transport_only.is_.return_value = "FAKE_FILTER_CLAUSE"
    monkeypatch.setattr(structure_service, "FeeStructure", fake_model)

    result = structure_service.list_fee_structures()
    assert result == []
    # The transport-off path must invoke .filter(...) with the is_transport_only clause.
    assert captured.get("filter_called") is True


def test_list_fee_structures_includes_transport_when_enabled(monkeypatch):
    monkeypatch.setattr(ff_mod, "is_feature_enabled", lambda _t, _k: True)
    monkeypatch.setattr(structure_service, "get_tenant_id", lambda: "tenant-1")

    fake_query = MagicMock()
    fake_query.filter_by.return_value = fake_query
    fake_query.order_by.return_value = fake_query
    fake_query.all.return_value = []
    fake_query.filter.side_effect = AssertionError(
        "Should not apply is_transport_only filter when transport is on"
    )

    fake_model = MagicMock()
    fake_model.query = fake_query
    monkeypatch.setattr(structure_service, "FeeStructure", fake_model)

    result = structure_service.list_fee_structures()
    assert result == []


def test_list_student_fees_excludes_transport_subquery_when_transport_off(monkeypatch):
    monkeypatch.setattr(ff_mod, "is_feature_enabled", lambda _t, k: k != "transport")
    monkeypatch.setattr(student_fee_service, "get_tenant_id", lambda: "tenant-1")

    captured = {"in_called": False}

    fake_q = MagicMock()
    fake_q.filter_by.return_value = fake_q
    fake_q.join.return_value = fake_q
    fake_q.order_by.return_value = fake_q
    fake_q.all.return_value = []

    def _filter(*_args, **_kw):
        captured["in_called"] = True
        return fake_q

    fake_q.filter.side_effect = _filter

    # Replace StudentFee module-level — `.query` access on a real
    # Flask-SQLAlchemy model needs app context, so we swap the symbol.
    fake_student_fee = MagicMock()
    fake_student_fee.query = fake_q
    monkeypatch.setattr(student_fee_service, "StudentFee", fake_student_fee)

    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value = MagicMock()
    monkeypatch.setattr(student_fee_service.db, "session", fake_session)

    result = student_fee_service.list_student_fees()
    assert result == []
    # Transport-off path must apply the exclusion filter.
    assert captured["in_called"] is True
