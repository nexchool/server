"""The dashboard shows each person only the sections they may act on.

`dashboard.read` is one permission over an aggregate that carries the whole
school: headcounts, today's attendance, the alert list, the finance position
and transport. Anyone holding it received all of it. That was tolerable while
only a School Admin held it, and stopped being tolerable when sub-admins
arrived: a finance officer, a hostel warden and a transport manager each hold
`dashboard.read` now, and each has business with one slice of that payload.

Hiding the cards in the browser would not have been an answer. The response is
readable in devtools, so a finance officer would still have been handed roll
counts and bus occupancy — `.claude/rules/security-guardrails.md`: "Never
return more data than the client needs." The composition therefore happens
server-side, and these tests read the payload, not the page.

Two absences that must not be confused, and are asserted apart below:
`enabled: False` means the school is not on that plan; `visible: False` means
this person may not see it. Telling a finance officer that Transport is not
part of their school's plan would be a lie about the school in order to
describe a fact about them.
"""

from __future__ import annotations

import uuid

import pytest

from tests.test_dashboard_authorization import _account_with, _get_dashboard


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _payload(client, tenant, token) -> dict:
    response = _get_dashboard(client, tenant, token)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


# ---------------------------------------------------------------------------
# One module in, one module out
# ---------------------------------------------------------------------------

def test_a_finance_officer_sees_finance_and_not_the_rest(client, db_session, tenant):
    """The whole point: the sub-admin the School Admin made for the fees desk."""
    _user, token = _account_with(
        db_session, tenant, "dashboard.read", "finance.read", name="Fees Desk"
    )

    data = _payload(client, tenant, token)

    assert data["finance"].get("visible") is not False
    assert data["overview"] == {"visible": False}
    assert data["transport"] == {"visible": False}
    assert data["today"] == {"visible": False}


def test_a_warden_does_not_receive_the_schools_finances(client, db_session, tenant):
    """A hostel warden holding dashboard.read must not be handed the money."""
    _user, token = _account_with(
        db_session, tenant, "dashboard.read", "hostel.read", name="Warden"
    )

    data = _payload(client, tenant, token)

    assert data["finance"] == {"visible": False}
    # Not merely absent from the rendering — absent from the response.
    assert b"total_collected" not in _get_dashboard(client, tenant, token).data


def test_a_transport_manager_sees_transport_only(client, db_session, tenant):
    _user, token = _account_with(
        db_session, tenant, "dashboard.read", "transport.dashboard.read",
        name="Transport",
    )

    data = _payload(client, tenant, token)

    assert data["transport"].get("visible") is not False
    assert data["finance"] == {"visible": False}
    assert data["overview"] == {"visible": False}


def test_a_school_admin_still_sees_everything(client, db_session, tenant):
    """The change must not cost the principal their dashboard."""
    _user, token = _account_with(
        db_session, tenant, "dashboard.read", "student.read.all", "teacher.read",
        "class.read", "attendance.read.all", "finance.read",
        "transport.dashboard.read", "holiday.read", name="Principal",
    )

    data = _payload(client, tenant, token)

    for section in ("overview", "today", "finance", "transport", "actions"):
        assert data[section].get("visible") is not False, section


def test_manage_implies_the_sections_read(client, db_session, tenant):
    """`finance.manage` covers `finance.read`, the rule used everywhere else."""
    _user, token = _account_with(
        db_session, tenant, "dashboard.read", "finance.manage", name="Bursar"
    )

    assert _payload(client, tenant, token)["finance"].get("visible") is not False


# ---------------------------------------------------------------------------
# The alert list is a list of other people's problems
# ---------------------------------------------------------------------------

def test_alerts_carry_only_the_rows_the_caller_could_open(client, db_session, tenant):
    _user, token = _account_with(
        db_session, tenant, "dashboard.read", "finance.read", name="Fees Desk"
    )

    alerts = _payload(client, tenant, token)["alerts"]

    assert "overdue_fees_students" in alerts
    assert "timetable_conflicts" not in alerts
    assert "students_without_class" not in alerts


def test_the_issue_count_counts_only_what_was_shown(client, db_session, tenant):
    """A badge reading 7 over a list of 2 is worse than no badge at all."""
    _user, token = _account_with(
        db_session, tenant, "dashboard.read", "finance.read", name="Fees Desk"
    )

    alerts = _payload(client, tenant, token)["alerts"]

    assert alerts["total_issues"] == sum(
        value for key, value in alerts.items() if key != "total_issues"
    )


# ---------------------------------------------------------------------------
# "Not on your plan" and "not yours to see" are different sentences
# ---------------------------------------------------------------------------

def test_a_permitted_but_unlicensed_module_reads_as_disabled(
    client, db_session, tenant, monkeypatch
):
    """Someone who may see transport, at a school that has not bought it."""
    from core import feature_flags

    monkeypatch.setattr(
        feature_flags, "is_feature_enabled",
        lambda tenant_id, key: key != "transport",
    )
    from modules.dashboard import service

    monkeypatch.setattr(service, "is_feature_enabled", feature_flags.is_feature_enabled)

    _user, token = _account_with(
        db_session, tenant, "dashboard.read", "transport.dashboard.read",
        name="Transport",
    )

    assert _payload(client, tenant, token)["transport"] == {"enabled": False}


def test_a_forbidden_module_never_reads_as_disabled(client, db_session, tenant):
    """The finance officer must not be told transport is off their school's plan."""
    _user, token = _account_with(
        db_session, tenant, "dashboard.read", "finance.read", name="Fees Desk"
    )

    transport = _payload(client, tenant, token)["transport"]

    assert transport == {"visible": False}
    assert "enabled" not in transport


# ---------------------------------------------------------------------------
# The grant that makes any of this reachable
# ---------------------------------------------------------------------------

def test_every_sub_admin_can_open_the_dashboard():
    """Before this, no module in the catalog granted `dashboard.read`.

    So every sub-admin ever created got a 403 on the screen the app opens on,
    while the sidebar showed them the link.
    """
    from modules.sub_admins.catalog import expand_selection

    granted = expand_selection([{"key": "finance", "level": "view"}])

    assert "dashboard.read" in granted


def test_a_sub_admin_with_no_modules_gets_nothing():
    """The baseline rides along with a real grant; it is not a grant itself."""
    from modules.sub_admins.catalog import expand_selection

    assert expand_selection([]) == set()
    assert expand_selection([{"key": "finance", "level": "none"}]) == set()
