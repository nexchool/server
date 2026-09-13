"""The term and the payments, as the panel writes them and the school reads them.

The operator sets the term and records payments under /api/platform; the
school reads its term in the subscription state and its payments under
/api/subscription, both behind `subscription.read`.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from modules.auth.services import generate_access_token
from tests.auth._characterization import grant_permissions, make_tenant, make_user


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _platform_admin(db_session, tenant):
    operator = make_user(db_session, tenant, password="Platform12345",
                         email=f"ops-{uuid.uuid4().hex[:8]}@nexchool.test",
                         is_platform_admin=True)
    return {"Authorization": f"Bearer {generate_access_token(operator)}"}


def _school_user(db_session, tenant, *, permissions):
    user = make_user(db_session, tenant, password="Member12345")
    grant_permissions(db_session, tenant, user, permissions)
    return {"Authorization": f"Bearer {generate_access_token(user)}",
            "X-Tenant-ID": tenant.id}


def test_the_operator_sets_the_term_and_reads_it_back_with_standing(client, db_session):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)
    due = date.today() + timedelta(days=100)

    patched = client.patch(f"/api/platform/tenants/{tenant.id}/subscription", headers=headers,
                           json={"subscription_starts_on": "2026-06-01",
                                 "subscription_due_on": due.isoformat(),
                                 "grace_days": 10, "auto_suspend_after_grace": False})
    assert patched.status_code == 200, patched.get_json()

    body = client.get(f"/api/platform/tenants/{tenant.id}/subscription", headers=headers).get_json()["data"]
    assert body["subscription_starts_on"] == "2026-06-01"
    assert body["subscription_due_on"] == due.isoformat()
    assert body["grace_days"] == 10
    assert body["auto_suspend_after_grace"] is False
    assert body["term"]["standing"] == "current"
    assert body["term"]["grace_ends_on"] == (due + timedelta(days=10)).isoformat()


def test_grace_days_must_be_a_whole_number_of_days(client, db_session):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)
    r = client.patch(f"/api/platform/tenants/{tenant.id}/subscription", headers=headers,
                     json={"grace_days": -1})
    assert r.status_code == 400
    assert "grace_days" in r.get_json()["message"]


def test_the_operator_records_a_payment_that_renews_the_term(client, db_session):
    tenant = make_tenant(db_session)
    tenant.subscription_due_on = date(2026, 6, 1)
    tenant.status = "suspended"
    db_session.flush()
    headers = _platform_admin(db_session, tenant)

    r = client.post(f"/api/platform/tenants/{tenant.id}/payments", headers=headers,
                    json={"amount": 190600, "paid_on": "2026-06-10", "method": "bank_transfer",
                          "reference": "NEFT-8812", "covers_from": "2026-06-01",
                          "covers_to": "2027-05-31", "note": "Annual renewal",
                          "next_due_on": "2027-06-01"})
    assert r.status_code == 201, r.get_json()
    payment = r.get_json()["data"]["payment"]
    assert payment["amount"] == 190600.0
    assert payment["reference"] == "NEFT-8812"
    assert r.get_json()["data"]["subscription"]["subscription_due_on"] == "2027-06-01"
    assert r.get_json()["data"]["subscription"]["status"] == "active"

    listed = client.get(f"/api/platform/tenants/{tenant.id}/payments", headers=headers).get_json()["data"]
    assert [p["id"] for p in listed["payments"]] == [payment["id"]]


def test_a_bad_payment_is_refused_with_the_reason(client, db_session):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)
    r = client.post(f"/api/platform/tenants/{tenant.id}/payments", headers=headers,
                    json={"amount": 0, "paid_on": "2026-06-10", "method": "cash"})
    assert r.status_code == 400
    assert "greater than zero" in r.get_json()["message"]


def test_the_operator_voids_a_payment_with_a_reason(client, db_session):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)
    created = client.post(f"/api/platform/tenants/{tenant.id}/payments", headers=headers,
                          json={"amount": 100, "paid_on": "2026-06-10", "method": "cash"})
    pid = created.get_json()["data"]["payment"]["id"]

    refused = client.post(f"/api/platform/tenants/{tenant.id}/payments/{pid}/void",
                          headers=headers, json={"reason": ""})
    assert refused.status_code == 400

    voided = client.post(f"/api/platform/tenants/{tenant.id}/payments/{pid}/void",
                         headers=headers, json={"reason": "Wrong school"})
    assert voided.status_code == 200
    assert voided.get_json()["data"]["payment"]["void_reason"] == "Wrong school"


def test_the_school_reads_its_term_and_its_payments_read_only(client, db_session):
    tenant = make_tenant(db_session)
    tenant.subscription_starts_on = date(2026, 6, 1)
    tenant.subscription_due_on = date.today() - timedelta(days=2)
    db_session.flush()
    ops = _platform_admin(db_session, tenant)
    client.post(f"/api/platform/tenants/{tenant.id}/payments", headers=ops,
                json={"amount": 5000, "paid_on": "2026-03-01", "method": "upi", "reference": "UPI-1"})
    headers = _school_user(db_session, tenant, permissions=("subscription.read",))

    state = client.get("/api/subscription/state", headers=headers).get_json()["data"]
    assert state["subscription"]["reason"] == "PaymentDue"
    assert state["term"]["standing"] == "payment_due"
    assert state["term"]["grace_ends_on"] == (date.today() + timedelta(days=5)).isoformat()

    payments = client.get("/api/subscription/payments", headers=headers).get_json()["data"]
    assert payments["payments"][0]["reference"] == "UPI-1"
    # No way to write from the school side.
    assert client.post("/api/subscription/payments", headers=headers, json={}).status_code in (403, 404, 405)


def test_a_teacher_sees_neither_term_details_nor_payments(client, db_session):
    tenant = make_tenant(db_session)
    headers = _school_user(db_session, tenant, permissions=("student.read.all",))
    state = client.get("/api/subscription/state", headers=headers).get_json()["data"]
    assert "term" not in state
    assert client.get("/api/subscription/payments", headers=headers).status_code == 403
