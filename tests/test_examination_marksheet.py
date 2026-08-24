"""The marksheet a school hands a parent.

The one thing this document must never do is follow `is_current`. Every test
below is ultimately about that: what is printed is the published version, and a
revision that has been calculated but not issued is not printed at all.
"""

from __future__ import annotations

import uuid

import pytest

from modules.examinations import (
    corrections_service,
    marks_service,
    marksheet_service,
    publication_service,
    results_service,
    revision_service,
)
from modules.examinations.models import (
    MARK_ABSENT,
    MARK_EXEMPTED,
    MARK_MALPRACTICE,
    MARK_PRESENT,
)

from tests.test_examination_marks import (  # noqa: F401
    _new_id,
    ctx,
    cycles,
    exam_type,
    school,
    year,
)
from tests.test_examination_graphql import (  # noqa: F401
    EXAMINATIONS_ON,
    examinations_enabled,
    _read_as,
    _signed_in,
    _signed_in_at,
    client,
)
from tests.test_examination_results import (  # noqa: F401
    _band,
    _exam,
    _mark,
    _paper_spec,
    _papers,
    _scheme,
)

URL = "/api/examinations/{}/students/{}/marksheet"


def _headers(tenant, token):
    return {
        "X-Tenant-Subdomain": tenant.subdomain,
        "Authorization": f"Bearer {token}",
    }


@pytest.fixture
def officer(db_session, tenant):
    return _signed_in(
        db_session, tenant,
        permissions=[
            "examination.read", "examination.publish",
            "assessment.manage", "assessment.update",
        ],
    )


@pytest.fixture
def published(ctx, tenant, cycles, exam_type, school, officer):
    """Riya 88, Dev absent, Meera exempted — calculated, locked, published."""
    _user, _token = officer
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A", 60, 100, is_pass=True, sequence=1, point=9)
    _band(tenant, scheme, "F", 0, 59.99, is_pass=False, sequence=2)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    marks = {
        school["riya"].id: _mark(tenant, paper, school["riya"], MARK_PRESENT, 88),
        school["dev"].id: _mark(tenant, paper, school["dev"], MARK_ABSENT),
        school["meera"].id: _mark(tenant, paper, school["meera"], MARK_EXEMPTED),
    }
    assert results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=_user.id, commit=False
    )["success"] is True
    assert marks_service.lock_paper(
        paper.id, tenant.id, actor_user_id=_user.id, commit=False
    )["success"] is True
    assert publication_service.publish_results(
        examination.id, tenant.id, actor_user_id=_user.id, commit=False
    )["success"] is True
    return {"examination": examination, "paper": paper, "marks": marks,
            "user": _user}


def _model(tenant, published, student, **kwargs):
    return marksheet_service.marksheet_model(
        published["examination"].id, student.id, tenant.id, **kwargs
    )


# ---------------------------------------------------------------------------
# What the document says
# ---------------------------------------------------------------------------

def test_the_marksheet_reads_the_published_snapshot(
    ctx, tenant, school, published, officer
):
    built = _model(tenant, published, school["riya"])
    assert built["success"] is True, built
    sheet = built["marksheet"]

    assert sheet["student"]["full_name"] == "Riya Patel"
    assert sheet["student"]["admission_number"]
    assert sheet["examination"]["name"] == published["examination"].name
    assert sheet["result"]["version"] == 1
    assert sheet["result"]["published_at"] is not None
    assert sheet["result"]["is_superseded"] is False
    assert sheet["aggregate"]["percentage"] == 88.0
    assert sheet["grading"]["grade_label"] == "A"
    assert sheet["grading"]["grade_point"] == 9.0
    assert sheet["outcome"]["is_pass"] is True
    assert sheet["outcome"]["complete"] is True
    assert len(sheet["papers"]) == 1


@pytest.mark.parametrize("who,status,included", [
    ("dev", MARK_ABSENT, True),
    ("meera", MARK_EXEMPTED, False),
])
def test_the_five_states_print_as_themselves(
    ctx, tenant, school, published, officer, who, status, included
):
    """No reinterpretation at print time: absent still counts toward the
    maximum, exempted still leaves the calculation."""
    sheet = _model(tenant, published, school[who])["marksheet"]
    paper = sheet["papers"][0]
    assert paper["status"] == status
    assert paper["marks"] is None
    assert paper["included_in_total"] is included


def test_an_exempted_only_student_prints_no_percentage(
    ctx, tenant, school, published, officer
):
    """`total_max` is zero, so there is no percentage — and 0% would say they
    failed everything they were excused from."""
    sheet = _model(tenant, published, school["meera"])["marksheet"]
    assert sheet["aggregate"]["total_max"] == 0.0
    assert sheet["aggregate"]["percentage"] is None
    assert sheet["grading"]["grade_label"] is None


def test_the_render_model_is_plain_data(ctx, tenant, school, published, officer):
    """The renderer must not be able to reach back into the database, so
    nothing it receives may be an ORM row."""
    import json

    sheet = _model(tenant, published, school["riya"])["marksheet"]
    json.dumps(sheet)      # raises if a model object survived


# ---------------------------------------------------------------------------
# Official, never current
# ---------------------------------------------------------------------------

def test_an_unpublished_result_has_no_marksheet(
    ctx, tenant, cycles, exam_type, school, officer
):
    _user, _token = officer
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)
    results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=_user.id, commit=False
    )

    built = marksheet_service.marksheet_model(
        examination.id, school["riya"].id, tenant.id
    )
    assert built["success"] is False
    assert built["code"] == "RESULT_NOT_PUBLISHED"


def test_a_student_with_no_result_at_all_is_refused(
    ctx, tenant, school, published, officer
):
    built = _model(tenant, published, school["outsider"])
    assert built["success"] is False
    assert built["code"] == "RESULT_NOT_PUBLISHED"


def test_the_acceptance_journey_the_document_never_follows_is_current(
    ctx, tenant, school, published, officer
):
    """Publish v1 → print → correct → revise → print again (still v1) →
    publish v2 → print again (now v2), with v1 still reprintable."""
    _user, _token = officer
    examination = published["examination"]

    first = _model(tenant, published, school["riya"])["marksheet"]
    assert first["result"]["version"] == 1
    assert first["aggregate"]["percentage"] == 88.0

    raised = corrections_service.request_correction(
        tenant.id, published["marks"][school["riya"].id].id,
        to_status=MARK_PRESENT, to_marks=95, reason="Re-totalled",
        requested_by_user_id=_user.id, commit=False,
    )
    assert corrections_service.approve_correction(
        tenant.id, raised["correction"].id,
        decided_by_user_id=_user.id, commit=False,
    )["success"] is True

    assert revision_service.revise_result(
        examination.id, school["riya"].id, tenant.id,
        reason="Correction approved", actor_user_id=_user.id, commit=False,
    )["success"] is True

    # v2 is current. The marksheet must still print v1 — nobody has been told
    # about v2 yet.
    current = results_service.current_result(
        examination.id, school["riya"].id, tenant.id
    )
    assert current.version == 2 and current.published_at is None

    still_v1 = _model(tenant, published, school["riya"])["marksheet"]
    assert still_v1["result"]["version"] == 1
    assert still_v1["aggregate"]["percentage"] == 88.0

    assert revision_service.publish_revision(
        examination.id, school["riya"].id, tenant.id,
        actor_user_id=_user.id, commit=False,
    )["success"] is True

    now_v2 = _model(tenant, published, school["riya"])["marksheet"]
    assert now_v2["result"]["version"] == 2
    assert now_v2["aggregate"]["percentage"] == 95.0

    # And v1 is still retrievable, unchanged, and says it was superseded.
    reprint = _model(tenant, published, school["riya"], version=1)["marksheet"]
    assert reprint["result"]["version"] == 1
    assert reprint["aggregate"]["percentage"] == 88.0
    assert reprint["result"]["is_superseded"] is True


def test_an_unpublished_version_cannot_be_reprinted_by_asking_for_it(
    ctx, tenant, school, published, officer
):
    """The published-only rule holds however the version is named."""
    _user, _token = officer
    examination = published["examination"]
    raised = corrections_service.request_correction(
        tenant.id, published["marks"][school["riya"].id].id,
        to_status=MARK_PRESENT, to_marks=95, reason="Re-totalled",
        requested_by_user_id=_user.id, commit=False,
    )
    corrections_service.approve_correction(
        tenant.id, raised["correction"].id,
        decided_by_user_id=_user.id, commit=False,
    )
    revision_service.revise_result(
        examination.id, school["riya"].id, tenant.id,
        reason="Correction approved", actor_user_id=_user.id, commit=False,
    )

    built = _model(tenant, published, school["riya"], version=2)
    assert built["success"] is False
    assert built["code"] == "RESULT_NOT_PUBLISHED"


def test_the_frozen_grading_survives_a_band_edit(
    ctx, db_session, tenant, school, published, officer
):
    """A school redrawing its bands must not change a document already issued."""
    from modules.examinations.models import GradingBand

    before = _model(tenant, published, school["riya"])["marksheet"]["grading"]
    for band in GradingBand.query.filter_by(tenant_id=tenant.id).all():
        band.min_value = 0
        band.max_value = 100
        band.label = "REDRAWN"
    db_session.flush()

    after = _model(tenant, published, school["riya"])["marksheet"]["grading"]
    assert after == before
    assert after["grade_label"] == "A"


# ---------------------------------------------------------------------------
# Transport, authority and tenancy
# ---------------------------------------------------------------------------

def test_downloading_needs_the_read_key(
    ctx, client, tenant, db_session, school, published
):
    _user, token = _signed_in(db_session, tenant, permissions=["assessment.manage"])
    response = client.get(
        URL.format(published["examination"].id, school["riya"].id),
        headers=_headers(tenant, token),
    )
    assert response.status_code == 403


def test_an_unpublished_result_refuses_over_http(
    ctx, client, tenant, cycles, exam_type, school, officer
):
    _user, token = officer
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    response = client.get(
        URL.format(examination.id, school["riya"].id),
        headers=_headers(tenant, token),
    )
    assert response.status_code == 409
    assert response.get_json()["details"]["code"] == "RESULT_NOT_PUBLISHED"


def test_another_schools_marksheet_is_not_found(
    ctx, client, db_session, tenant, school, published, officer
):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex[:10]}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
        feature_flags=EXAMINATIONS_ON,
    )
    db_session.add(other)
    db_session.flush()
    _outsider, outsider_token = _signed_in_at(
        db_session, other, permissions=["examination.read"]
    )

    response = client.get(
        URL.format(published["examination"].id, school["riya"].id),
        headers=_headers(other, outsider_token),
    )
    assert response.status_code >= 400
    assert response.status_code != 200


def test_a_bad_version_argument_is_refused(
    ctx, client, tenant, school, published, officer
):
    _user, token = officer
    response = client.get(
        URL.format(published["examination"].id, school["riya"].id) + "?version=abc",
        headers=_headers(tenant, token),
    )
    assert response.status_code == 400


def test_the_download_returns_a_pdf_or_says_why_not(
    ctx, client, tenant, school, published, officer
):
    """WeasyPrint needs native libraries that are absent on some machines, so
    the route reports that rather than failing as if the result were wrong."""
    _user, token = officer
    response = client.get(
        URL.format(published["examination"].id, school["riya"].id),
        headers=_headers(tenant, token),
    )

    if response.status_code == 200:
        assert response.mimetype == "application/pdf"
        assert response.data[:4] == b"%PDF"
        assert "marksheet-" in response.headers["Content-Disposition"]
        assert "-v1.pdf" in response.headers["Content-Disposition"]
    else:
        assert response.status_code == 503
        assert response.get_json()["details"]["code"] == "PDF_UNAVAILABLE"
