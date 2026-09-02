"""The results board is marks, and marks answer to `assessment.*`.

`examinationResults` returns *every* student's result for one examination —
names, totals, percentages, grades. It was guarded by `examination.read`,
which is the wrong tier: that key means "may know which examinations exist"
and is held by the **Student and Parent profiles**, the Student one implied by
the relationship so every pupil holds it automatically.

The marking register one section above already had this right
(`requires_any('assessment.read.class', 'assessment.read.all',
'assessment.manage')`). The board simply did not copy it.

Under ADR-011 a household shares the pupil's login, so "a pupil could read it"
and "any parent could read every child's marks" are the same sentence.
"""

from __future__ import annotations

import uuid

import pytest

from graphql_api import GRAPHQL_PATH

BOARD = """
query Board($id: ID!) {
  examinationResults(examinationId: $id) { examinationId examinationName }
}
"""

#: Exactly what the Student and Parent profiles grant (rbac/catalog.py).
PUPIL_KEYS = ("assessment.read.self", "examination.read")


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def examinations_enabled(db_session, tenant):
    """A school that runs examinations is one whose super-admin turned them on."""
    tenant.feature_flags = {**(tenant.feature_flags or {}), "examinations": True}
    db_session.flush()
    return tenant


def _signed_in(db_session, tenant, *permissions):
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Someone",
    )
    db_session.add(user)
    db_session.flush()

    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Role-{suffix}")
    db_session.add(role)
    db_session.flush()
    for key in permissions:
        permission = Permission.query.filter_by(name=key).first()
        if permission is None:
            permission = Permission(id=f"perm-{uuid.uuid4().hex[:8]}", name=key)
            db_session.add(permission)
            db_session.flush()
        db_session.add(RolePermission(
            tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
        ))
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")
    return generate_access_token(user)


def _ask_board(client, tenant, token):
    return client.post(
        GRAPHQL_PATH,
        json={"query": BOARD, "variables": {"id": f"ex-{uuid.uuid4().hex[:12]}"}},
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {token}",
        },
    ).get_json()


def _refused(body) -> bool:
    """Did the *guard* stop this, as opposed to the examination not existing?"""
    return any(
        "permission" in (error.get("message") or "").lower()
        for error in body.get("errors", [])
    )


def test_a_pupil_cannot_read_every_childs_results(client, db_session, tenant):
    token = _signed_in(db_session, tenant, *PUPIL_KEYS)

    body = _ask_board(client, tenant, token)

    assert _refused(body), (
        "a pupil holding only `assessment.read.self` must not reach the board"
    )


def test_examination_read_alone_is_not_enough(client, db_session, tenant):
    """The key that means "examinations exist" must not unlock marks."""
    token = _signed_in(db_session, tenant, "examination.read")

    assert _refused(_ask_board(client, tenant, token))


def test_a_class_teacher_may_read_the_board(client, db_session, tenant):
    token = _signed_in(
        db_session, tenant, "examination.read", "assessment.read.class"
    )

    body = _ask_board(client, tenant, token)

    assert not _refused(body), body.get("errors")


def test_an_administrator_may_read_the_board(client, db_session, tenant):
    token = _signed_in(db_session, tenant, "examination.read", "assessment.manage")

    body = _ask_board(client, tenant, token)

    assert not _refused(body), body.get("errors")
