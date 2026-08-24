"""A subject offering may belong to one stream, or to all of them.

`subject_contexts` decides what a (programme, grade) studies. Before migration
108 Grade 11 Science and Grade 11 Commerce were the same (programme, grade), so
they resolved to the same subject set — and their examinations would have too.

NULL means "every stream", which is what every row written before 108 means and
what every row in a school with no streams means. That is why the backfill is
the absence of one.
"""

from __future__ import annotations

import uuid

import pytest
from flask import g

from modules.academic_programmes.models import AcademicProgramme
from modules.grades.models import Grade
from modules.streams.models import Stream
from modules.subject_contexts.models import SubjectContext
from modules.subject_contexts.services import list_contexts
from modules.subjects.models import Subject


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def programme(db_session, tenant):
    row = AcademicProgramme(
        id=_new_id("pr-"), tenant_id=tenant.id,
        name=f"Board-{uuid.uuid4().hex[:6]}", code=f"B{uuid.uuid4().hex[:6]}",
        board="CBSE",
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def grade(db_session, tenant):
    row = Grade(
        id=_new_id("gr-"), tenant_id=tenant.id,
        name=f"Grade-{uuid.uuid4().hex[:6]}", sequence=11,
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def streams(db_session, tenant):
    made = {}
    for index, name in enumerate(("Science", "Commerce")):
        row = Stream(
            id=_new_id("st-"), tenant_id=tenant.id,
            name=f"{name}-{uuid.uuid4().hex[:6]}", sequence=index,
        )
        db_session.add(row)
        made[name] = row
    db_session.flush()
    return made


def _subject(db_session, tenant, label):
    row = Subject(
        id=_new_id("sb-"), tenant_id=tenant.id,
        name=f"{label}-{uuid.uuid4().hex[:6]}", code=f"{label[:3].upper()}{uuid.uuid4().hex[:4]}",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _context(db_session, tenant, programme, grade, subject, stream=None):
    row = SubjectContext(
        id=_new_id("sc-"), tenant_id=tenant.id, programme_id=programme.id,
        grade_id=grade.id, subject_id=subject.id,
        stream_id=stream.id if stream else None,
        type="mandatory", default_weekly_periods=5, sort_order=0, is_active=True,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_science_and_commerce_study_different_subjects(
    ctx, db_session, tenant, programme, grade, streams
):
    english = _subject(db_session, tenant, "English")
    physics = _subject(db_session, tenant, "Physics")
    accountancy = _subject(db_session, tenant, "Accountancy")

    _context(db_session, tenant, programme, grade, english)  # every stream
    _context(db_session, tenant, programme, grade, physics, streams["Science"])
    _context(db_session, tenant, programme, grade, accountancy, streams["Commerce"])

    science = list_contexts(
        tenant.id, programme.id, grade.id, stream_id=streams["Science"].id
    )
    commerce = list_contexts(
        tenant.id, programme.id, grade.id, stream_id=streams["Commerce"].id
    )

    science_subjects = {c["subject_id"] for c in science}
    commerce_subjects = {c["subject_id"] for c in commerce}

    # Each stream studies its own subject and the shared one, never the other's.
    assert physics.id in science_subjects
    assert accountancy.id not in science_subjects
    assert accountancy.id in commerce_subjects
    assert physics.id not in commerce_subjects
    assert english.id in science_subjects and english.id in commerce_subjects


def test_a_null_stream_context_applies_everywhere(
    ctx, db_session, tenant, programme, grade, streams
):
    english = _subject(db_session, tenant, "English")
    _context(db_session, tenant, programme, grade, english)

    for stream in streams.values():
        rows = list_contexts(tenant.id, programme.id, grade.id, stream_id=stream.id)
        assert english.id in {c["subject_id"] for c in rows}

    # A section with no stream sees only the general offerings.
    streamless = list_contexts(tenant.id, programme.id, grade.id, stream_id=None)
    assert english.id in {c["subject_id"] for c in streamless}


def test_a_streamless_section_does_not_pick_up_stream_subjects(
    ctx, db_session, tenant, programme, grade, streams
):
    physics = _subject(db_session, tenant, "Physics")
    _context(db_session, tenant, programme, grade, physics, streams["Science"])

    rows = list_contexts(tenant.id, programme.id, grade.id, stream_id=None)
    assert physics.id not in {c["subject_id"] for c in rows}


def test_omitting_the_stream_lists_every_offering(
    ctx, db_session, tenant, programme, grade, streams
):
    """The administrator's view of the curriculum, not one section's."""
    physics = _subject(db_session, tenant, "Physics")
    accountancy = _subject(db_session, tenant, "Accountancy")
    _context(db_session, tenant, programme, grade, physics, streams["Science"])
    _context(db_session, tenant, programme, grade, accountancy, streams["Commerce"])

    rows = list_contexts(tenant.id, programme.id, grade.id)
    found = {c["subject_id"] for c in rows}
    assert {physics.id, accountancy.id} <= found


def test_a_context_cannot_name_another_schools_stream(
    ctx, db_session, tenant, programme, grade
):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY
    from modules.subject_contexts.services import _validate_stream

    other = Tenant(
        id=_new_id("t-"), name="Other School",
        subdomain=f"test-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    theirs = Stream(
        id=_new_id("st-"), tenant_id=other.id,
        name=f"Theirs-{uuid.uuid4().hex[:6]}", sequence=1,
    )
    db_session.add(theirs)
    db_session.flush()

    assert _validate_stream(tenant.id, theirs.id) is not None
