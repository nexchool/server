"""Scheduling examinations over GraphQL — the module's first transport.

Eight slices of invariants sit behind these fields, so most of what is tested
here is that the transport **does not** re-decide any of them: a refusal the
service already produces must arrive as the right kind of GraphQL error, and a
fan-out that fails halfway must leave nothing behind.

The fixtures build a real school — tenant, cycle, sections, offerings — rather
than a toy, because the wizard's whole job is resolving offerings and a fixture
without them would test nothing.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from graphql_api import GRAPHQL_PATH
from modules.examinations.models import EXAM_CANCELLED, EXAM_SCHEDULED, Examination

from tests.test_examination_marks import (  # noqa: F401
    _new_id,
    ctx,
    cycles,
    exam_type,
    school,
    year,
)


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _headers(tenant, token):
    return {
        "X-Tenant-Subdomain": tenant.subdomain,
        "Authorization": f"Bearer {token}",
    }


def _errors(response):
    """The *kind* of each error — what a client branches on."""
    return [
        e.get("extensions", {}).get("code")
        for e in response.get_json().get("errors", [])
    ]


def _codes(response):
    """The domain's own refusal codes, carried in details."""
    return [
        (e.get("extensions", {}).get("details") or {}).get("code")
        for e in response.get_json().get("errors", [])
    ]


def _messages(response):
    return " ".join(e["message"] for e in response.get_json().get("errors", []))


def _data(response):
    body = response.get_json()
    assert "errors" not in body, body.get("errors")
    return body["data"]


def _signed_in(db_session, tenant, *, permissions=()):
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import employ_for, grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Examinations Officer",
    )
    db_session.add(user)
    db_session.flush()
    employ_for(user, employee_number=f"EMP-{suffix}")

    if permissions:
        role = Role(
            id=f"r-{uuid.uuid4().hex[:8]}", tenant_id=tenant.id,
            name=f"Exams-{suffix}",
        )
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
        grant_profile_to(user, role.id)

    return user, generate_access_token(user)




# The module ships switched off (`DEFAULT_OFF_FEATURES`), so a school that
# runs examinations is one whose super-admin turned them on. Every transport
# test needs that to be true of its tenant — the alternative is 111 tests all
# asserting the same 403. The gate itself is tested in
# `test_examination_feature_flag.py`, which is where turning it *off* belongs.
EXAMINATIONS_ON = {"examinations": True}


@pytest.fixture(autouse=True)
def examinations_enabled(db_session, tenant):
    """Switch the module on for the tenant under test."""
    tenant.feature_flags = {**(tenant.feature_flags or {}), **EXAMINATIONS_ON}
    db_session.flush()
    return tenant


def _read_as(school):
    """Point the ORM tenant scope at this school before a direct DB assertion.

    Posting through the test client resolves a tenant into the enclosing app
    context — `g` lives on the app context, and the client reuses the one the
    `ctx` fixture pushed — so after a request made as another school, every
    scoped query in the test silently reads that school instead. Nothing warns;
    rows simply stop being found.
    """
    g.tenant_id = school.id


def _signed_in_at(db_session, other_tenant, *, permissions=()):
    """Sign somebody in at a *different* school than the one in context.

    The scope has to move with them. `ensure_staff` is idempotent by looking
    for existing employment, and that lookup goes through the ORM tenant scope
    — so creating a foreign-tenant account while `g.tenant_id` still names this
    school makes the lookup miss and insert a second employment, which the
    unique constraint then refuses. The scope is what makes the helper
    idempotent, so it has to be pointed at the right school.
    """
    previous = getattr(g, "tenant_id", None)
    g.tenant_id = other_tenant.id
    try:
        return _signed_in(db_session, other_tenant, permissions=permissions)
    finally:
        g.tenant_id = previous


@pytest.fixture
def reader(db_session, tenant):
    return _signed_in(db_session, tenant, permissions=["examination.read"])


@pytest.fixture
def scheduler(db_session, tenant):
    """Both keys: every write here also reads the result back."""
    return _signed_in(
        db_session, tenant,
        permissions=["examination.read", "examination.manage"],
    )


def _post(client, tenant, token, query, variables=None):
    return client.post(
        GRAPHQL_PATH,
        json={"query": query, "variables": variables or {}},
        headers=_headers(tenant, token),
    )


CREATE = """
mutation Create($input: CreateExaminationInput!) {
  createExamination(input: $input) {
    id name status academicCycleId
    papers { id classId classSubjectId maxMarks passMarks examDate componentLabel }
    classesSitting
  }
}
"""

LIST = """
query List($cycle: ID, $status: String, $limit: Int!, $offset: Int!) {
  examinations(academicCycleId: $cycle, status: $status, limit: $limit, offset: $offset) {
    nodes { id name status }
    hasNextPage
    totalCount
  }
}
"""

DETAIL = """
query Detail($id: ID!) {
  examination(id: $id) {
    id name status
    papers { id classId }
    classesSitting
    timeline { eventName note }
  }
}
"""

SCHEDULE = "mutation S($id: ID!) { scheduleExamination(id: $id) { id status } }"
CANCEL = """
mutation C($id: ID!, $reason: String!) {
  cancelExamination(id: $id, reason: $reason) { id status }
}
"""
UPDATE = """
mutation U($id: ID!, $input: UpdateExaminationInput!) {
  updateExamination(id: $id, input: $input) { id name }
}
"""


def _subject_set(school, *, sections, subjects, day=6):
    return {
        "classIds": [s.id for s in sections],
        "subjects": [
            {
                "subjectId": subject_id,
                "maxMarks": 100,
                "passMarks": 35,
                "examDate": date(2026, 7, day).isoformat(),
            }
            for subject_id in subjects
        ],
    }


def _create_input(cycles, exam_type, name=None, subject_set=None):
    payload = {
        "academicCycleId": cycles["main"].id,
        "examTypeId": exam_type.id,
        "name": name or f"Half Yearly {uuid.uuid4().hex[:5]}",
    }
    if subject_set:
        payload["subjectSet"] = subject_set
    return payload


# ---------------------------------------------------------------------------
# Authorization — every field declares what it requires
# ---------------------------------------------------------------------------

def test_reading_without_signing_in_is_refused(client, tenant, ctx):
    response = client.post(
        GRAPHQL_PATH,
        json={"query": LIST, "variables": {"limit": 10, "offset": 0}},
        headers={"X-Tenant-Subdomain": tenant.subdomain},
    )
    assert "UNAUTHENTICATED" in _errors(response)


def test_reading_without_the_authority_is_refused(client, tenant, db_session, ctx):
    _user, token = _signed_in(db_session, tenant)      # signed in, no keys
    response = _post(client, tenant, token, LIST, {"limit": 10, "offset": 0})
    assert "FORBIDDEN" in _errors(response)


def test_a_reader_cannot_create_an_examination(
    client, tenant, db_session, cycles, exam_type, reader, ctx
):
    """`examination.read` is "View examinations". Creating is a different key."""
    _user, token = reader
    response = _post(client, tenant, token, CREATE,
                     {"input": _create_input(cycles, exam_type)})
    assert "FORBIDDEN" in _errors(response)
    assert Examination.query.filter_by(tenant_id=tenant.id).count() == 0


def test_scheduling_and_cancelling_need_the_manage_key(
    client, tenant, db_session, cycles, exam_type, school, reader, scheduler, ctx
):
    _u, manage_token = scheduler
    created = _data(_post(client, tenant, manage_token, CREATE, {"input": _create_input(
        cycles, exam_type,
        subject_set=_subject_set(school, sections=[school["ten_a"]],
                                 subjects=[school["maths"].subject_id]),
    )}))["createExamination"]

    _u2, read_token = reader
    assert "FORBIDDEN" in _errors(
        _post(client, tenant, read_token, SCHEDULE, {"id": created["id"]})
    )
    assert "FORBIDDEN" in _errors(
        _post(client, tenant, read_token, CANCEL,
              {"id": created["id"], "reason": "no"})
    )


# ---------------------------------------------------------------------------
# The create wizard — one subject set, fanned across sections
# ---------------------------------------------------------------------------

def test_one_subject_set_fans_across_sections(
    client, db_session, tenant, year, cycles, exam_type, school, scheduler, ctx
):
    """The roadmap's acceptance criterion: two sections × two subjects in one
    pass produces four papers, and the client never names a `class_id`."""
    from modules.classes.models import Class
    from tests.test_examination_marks import _offering

    ten_b = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section="10B", name="Section 10B",
        academic_year_id=year.id, academic_cycle_id=cycles["main"].id,
    )
    db_session.add(ten_b)
    db_session.flush()
    # 10B teaches the same two subjects as 10A.
    for subject_id in (school["maths"].subject_id, school["science"].subject_id):
        db_session.add(type(school["maths"])(
            id=_new_id("cs-"), tenant_id=tenant.id, class_id=ten_b.id,
            subject_id=subject_id, weekly_periods=5, status="active",
        ))
    db_session.flush()

    _user, token = scheduler
    created = _data(_post(client, tenant, token, CREATE, {"input": _create_input(
        cycles, exam_type,
        subject_set=_subject_set(
            school, sections=[school["ten_a"], ten_b],
            subjects=[school["maths"].subject_id, school["science"].subject_id],
        ),
    )}))["createExamination"]

    assert len(created["papers"]) == 4
    assert set(created["classesSitting"]) == {school["ten_a"].id, ten_b.id}
    # Each paper's class came off its offering, not off the request.
    assert {p["classId"] for p in created["papers"]} == {school["ten_a"].id, ten_b.id}
    assert all(p["maxMarks"] == 100.0 for p in created["papers"])


def test_a_section_that_does_not_teach_a_subject_is_named_not_skipped(
    client, db_session, tenant, year, cycles, exam_type, school, scheduler, ctx
):
    """Silently dropping it would schedule an examination the school believes
    covers a class it does not."""
    from modules.classes.models import Class

    bare = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section="10Z", name="Section 10Z",
        academic_year_id=year.id, academic_cycle_id=cycles["main"].id,
    )
    db_session.add(bare)
    db_session.flush()

    _user, token = scheduler
    response = _post(client, tenant, token, CREATE, {"input": _create_input(
        cycles, exam_type,
        subject_set=_subject_set(school, sections=[school["ten_a"], bare],
                                 subjects=[school["maths"].subject_id]),
    )})
    assert "NOT_FOUND" in _errors(response)
    assert "10Z" in _messages(response)
    assert Examination.query.filter_by(tenant_id=tenant.id).count() == 0


def test_one_bad_paper_creates_no_examination_at_all(
    client, tenant, db_session, cycles, exam_type, school, scheduler, ctx
):
    """The service's atomic path, reached through the transport: a date outside
    the cycle on the second subject takes the examination with it."""
    _user, token = scheduler
    payload = _create_input(
        cycles, exam_type,
        subject_set=_subject_set(school, sections=[school["ten_a"]],
                                 subjects=[school["maths"].subject_id]),
    )
    payload["subjectSet"]["subjects"].append({
        "subjectId": school["science"].subject_id,
        "maxMarks": 100,
        "examDate": date(2030, 7, 6).isoformat(),      # long after the cycle
    })

    response = _post(client, tenant, token, CREATE, {"input": payload})
    assert _errors(response) == ["VALIDATION_ERROR"]
    assert "DATE_OUTSIDE_CYCLE" in _codes(response)
    assert Examination.query.filter_by(tenant_id=tenant.id).count() == 0
    from modules.examinations.models import ExamPaper
    assert ExamPaper.query.filter_by(tenant_id=tenant.id).count() == 0


def test_a_duplicate_paper_in_one_request_is_a_conflict(
    client, tenant, cycles, exam_type, school, scheduler, ctx
):
    _user, token = scheduler
    payload = _create_input(
        cycles, exam_type,
        subject_set=_subject_set(school, sections=[school["ten_a"]],
                                 subjects=[school["maths"].subject_id,
                                           school["maths"].subject_id]),
    )
    response = _post(client, tenant, token, CREATE, {"input": payload})
    assert "CONFLICT" in _errors(response)


def test_an_unknown_cycle_is_not_found(
    client, tenant, cycles, exam_type, scheduler, ctx
):
    _user, token = scheduler
    payload = _create_input(cycles, exam_type)
    payload["academicCycleId"] = "cy-nope"
    response = _post(client, tenant, token, CREATE, {"input": payload})
    assert "NOT_FOUND" in _errors(response)


def test_an_examination_with_no_sections_is_refused(
    client, tenant, cycles, exam_type, school, scheduler, ctx
):
    _user, token = scheduler
    payload = _create_input(cycles, exam_type)
    payload["subjectSet"] = {
        "classIds": [],
        "subjects": [{"subjectId": school["maths"].subject_id, "maxMarks": 100}],
    }
    response = _post(client, tenant, token, CREATE, {"input": payload})
    assert "VALIDATION_ERROR" in _errors(response)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def test_the_list_pages_and_counts(
    client, tenant, cycles, exam_type, school, scheduler, ctx
):
    _user, token = scheduler
    for index in range(3):
        _data(_post(client, tenant, token, CREATE,
                    {"input": _create_input(cycles, exam_type, name=f"Exam {index}")}))

    page = _data(_post(client, tenant, token, LIST,
                       {"limit": 2, "offset": 0}))["examinations"]
    assert len(page["nodes"]) == 2
    assert page["hasNextPage"] is True
    assert page["totalCount"] == 3

    second = _data(_post(client, tenant, token, LIST,
                         {"limit": 2, "offset": 2}))["examinations"]
    assert len(second["nodes"]) == 1
    assert second["hasNextPage"] is False


def test_the_list_filters_by_status(
    client, tenant, cycles, exam_type, school, scheduler, ctx
):
    _user, token = scheduler
    created = _data(_post(client, tenant, token, CREATE, {"input": _create_input(
        cycles, exam_type,
        subject_set=_subject_set(school, sections=[school["ten_a"]],
                                 subjects=[school["maths"].subject_id]),
    )}))["createExamination"]
    _data(_post(client, tenant, token, SCHEDULE, {"id": created["id"]}))
    _data(_post(client, tenant, token, CREATE, {"input": _create_input(cycles, exam_type)}))

    scheduled = _data(_post(client, tenant, token, LIST, {
        "limit": 10, "offset": 0, "status": EXAM_SCHEDULED,
    }))["examinations"]
    assert [n["id"] for n in scheduled["nodes"]] == [created["id"]]
    assert scheduled["totalCount"] == 1


def test_an_empty_list_is_not_an_error(client, tenant, scheduler, ctx):
    _user, token = scheduler
    page = _data(_post(client, tenant, token, LIST,
                       {"limit": 10, "offset": 0}))["examinations"]
    assert page["nodes"] == []
    assert page["totalCount"] == 0
    assert page["hasNextPage"] is False


def test_the_detail_carries_papers_sections_and_history(
    client, tenant, cycles, exam_type, school, scheduler, ctx
):
    _user, token = scheduler
    created = _data(_post(client, tenant, token, CREATE, {"input": _create_input(
        cycles, exam_type,
        subject_set=_subject_set(school, sections=[school["ten_a"]],
                                 subjects=[school["maths"].subject_id]),
    )}))["createExamination"]
    _data(_post(client, tenant, token, SCHEDULE, {"id": created["id"]}))

    detail = _data(_post(client, tenant, token, DETAIL,
                         {"id": created["id"]}))["examination"]
    assert len(detail["papers"]) == 1
    assert detail["classesSitting"] == [school["ten_a"].id]
    assert [e["eventName"] for e in detail["timeline"]] == ["ExaminationScheduled"]


def test_an_unknown_examination_is_null_not_an_error(client, tenant, scheduler, ctx):
    _user, token = scheduler
    body = _data(_post(client, tenant, token, DETAIL, {"id": "ex-nope"}))
    assert body["examination"] is None


# ---------------------------------------------------------------------------
# Lifecycle over the wire
# ---------------------------------------------------------------------------

def test_scheduling_an_examination_with_no_papers_is_refused(
    client, tenant, cycles, exam_type, scheduler, ctx
):
    _user, token = scheduler
    created = _data(_post(client, tenant, token, CREATE,
                          {"input": _create_input(cycles, exam_type)}))["createExamination"]
    response = _post(client, tenant, token, SCHEDULE, {"id": created["id"]})
    assert "NO_PAPERS" in _codes(response)


def test_scheduling_twice_is_a_conflict(
    client, tenant, cycles, exam_type, school, scheduler, ctx
):
    _user, token = scheduler
    created = _data(_post(client, tenant, token, CREATE, {"input": _create_input(
        cycles, exam_type,
        subject_set=_subject_set(school, sections=[school["ten_a"]],
                                 subjects=[school["maths"].subject_id]),
    )}))["createExamination"]
    assert _data(_post(client, tenant, token, SCHEDULE,
                       {"id": created["id"]}))["scheduleExamination"]["status"] == EXAM_SCHEDULED

    response = _post(client, tenant, token, SCHEDULE, {"id": created["id"]})
    assert _errors(response) == ["CONFLICT"]
    assert _codes(response) == ["INVALID_TRANSITION"]


def test_cancelling_records_the_reason_and_the_event(
    client, tenant, cycles, exam_type, school, scheduler, ctx
):
    _user, token = scheduler
    created = _data(_post(client, tenant, token, CREATE, {"input": _create_input(
        cycles, exam_type,
        subject_set=_subject_set(school, sections=[school["ten_a"]],
                                 subjects=[school["maths"].subject_id]),
    )}))["createExamination"]

    cancelled = _data(_post(client, tenant, token, CANCEL, {
        "id": created["id"], "reason": "Flooding closed the campus",
    }))["cancelExamination"]
    assert cancelled["status"] == EXAM_CANCELLED

    detail = _data(_post(client, tenant, token, DETAIL,
                         {"id": created["id"]}))["examination"]
    events = [e for e in detail["timeline"] if e["eventName"] == "ExaminationCancelled"]
    assert len(events) == 1
    assert "Flooding" in events[0]["note"]


def test_cancelling_without_a_reason_is_refused(
    client, tenant, cycles, exam_type, scheduler, ctx
):
    _user, token = scheduler
    created = _data(_post(client, tenant, token, CREATE,
                          {"input": _create_input(cycles, exam_type)}))["createExamination"]
    response = _post(client, tenant, token, CANCEL,
                     {"id": created["id"], "reason": "   "})
    assert "VALIDATION_ERROR" in _errors(response)


def test_the_cycle_cannot_be_edited_through_the_transport(
    client, tenant, cycles, exam_type, scheduler, ctx
):
    """There is no `academicCycleId` on the update input at all — the schema
    refuses it before the service has to."""
    _user, token = scheduler
    created = _data(_post(client, tenant, token, CREATE,
                          {"input": _create_input(cycles, exam_type)}))["createExamination"]
    response = _post(client, tenant, token, UPDATE, {
        "id": created["id"],
        "input": {"academicCycleId": cycles["batch"].id},
    })
    assert response.get_json().get("errors"), "an unknown input field was accepted"


def test_renaming_an_examination_works(
    client, tenant, cycles, exam_type, scheduler, ctx
):
    _user, token = scheduler
    created = _data(_post(client, tenant, token, CREATE,
                          {"input": _create_input(cycles, exam_type)}))["createExamination"]
    renamed = _data(_post(client, tenant, token, UPDATE, {
        "id": created["id"], "input": {"name": "Renamed Half Yearly"},
    }))["updateExamination"]
    assert renamed["name"] == "Renamed Half Yearly"


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------

def test_another_schools_examination_is_invisible(
    client, db_session, tenant, cycles, exam_type, school, scheduler, ctx
):
    """The examination exists; a signed-in officer of another school must not
    see it in a list, in a detail, or in a count."""
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    _user, token = scheduler
    mine = _data(_post(client, tenant, token, CREATE,
                       {"input": _create_input(cycles, exam_type)}))["createExamination"]

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex[:10]}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
        feature_flags=EXAMINATIONS_ON,
    )
    db_session.add(other)
    db_session.flush()
    _outsider, outsider_token = _signed_in_at(
        db_session, other, permissions=["examination.read", "examination.manage"]
    )

    page = _data(_post(client, other, outsider_token, LIST,
                       {"limit": 10, "offset": 0}))["examinations"]
    assert page["nodes"] == []
    assert page["totalCount"] == 0

    detail = _data(_post(client, other, outsider_token, DETAIL, {"id": mine["id"]}))
    assert detail["examination"] is None


def test_another_school_cannot_schedule_or_cancel_my_examination(
    client, db_session, tenant, cycles, exam_type, school, scheduler, ctx
):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    _user, token = scheduler
    mine = _data(_post(client, tenant, token, CREATE, {"input": _create_input(
        cycles, exam_type,
        subject_set=_subject_set(school, sections=[school["ten_a"]],
                                 subjects=[school["maths"].subject_id]),
    )}))["createExamination"]

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex[:10]}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
        feature_flags=EXAMINATIONS_ON,
    )
    db_session.add(other)
    db_session.flush()
    _outsider, outsider_token = _signed_in_at(
        db_session, other, permissions=["examination.read", "examination.manage"]
    )

    assert "NOT_FOUND" in _errors(
        _post(client, other, outsider_token, SCHEDULE, {"id": mine["id"]})
    )
    assert "NOT_FOUND" in _errors(
        _post(client, other, outsider_token, CANCEL,
              {"id": mine["id"], "reason": "theirs"})
    )
    # A request through the test client resolves its own tenant into the
    # enclosing app context and leaves it there, so `g.tenant_id` now names the
    # *other* school and the ORM scope would hide my own row. Point the scope
    # back before reading — see `_read_as`.
    _read_as(tenant)
    assert Examination.query.filter_by(id=mine["id"]).first().status == "draft"


def test_the_exam_type_picker_is_tenant_scoped(
    client, db_session, tenant, exam_type, scheduler, ctx
):
    """Supporting data the wizard renders is scoped like everything else."""
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant
    from modules.examinations.models import ExamType

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex[:10]}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
        feature_flags=EXAMINATIONS_ON,
    )
    db_session.add(other)
    db_session.flush()
    db_session.add(ExamType(
        id=_new_id("et-"), tenant_id=other.id, name="Theirs", sequence=1,
    ))
    db_session.flush()

    _user, token = scheduler
    types = _data(_post(
        client, tenant, token, "{ examTypes { id name } }"
    ))["examTypes"]
    assert exam_type.id in [t["id"] for t in types]
    assert "Theirs" not in [t["name"] for t in types]
