"""The switch a super-admin uses to decide whether a school runs examinations.

The module ships **off** — `examinations` is in `DEFAULT_OFF_FEATURES`, so a
tenant that has never been asked the question does not get it. That is the
opposite of the rule for every other optional feature, and the exception is
deliberate: "missing means on" protects a school from losing a module it was
already using, and a module nobody has ever used has nothing to protect. Left
alone, the rule would switch examinations on for every school on the deploy
that introduced it.

What is tested here is the switch itself: that it is off unless somebody says
otherwise, that both transports close when it is off, and that the super-admin
panel is actually offered it. Every other examination test runs with the module
on, which is why they say so through the `examinations_enabled` fixture rather
than leaving it to a default.
"""

from __future__ import annotations

import uuid
from io import BytesIO

import pytest

from core.feature_flags import (
    DEFAULT_OFF_FEATURES,
    OPTIONAL_FEATURES,
    default_feature_flags,
    effective_flags,
    is_feature_enabled,
)

from tests.test_examination_graphql import (  # noqa: F401
    _errors,
    _post,
    _signed_in,
    client,
    LIST,
)
from tests.test_examination_marks import ctx  # noqa: F401

FEATURE = "examinations"
ALL_EXAM_PERMISSIONS = [
    "examination.read",
    "examination.manage",
    "examination.publish",
    "assessment.manage",
]


# --- the default ------------------------------------------------------------

def test_a_school_that_was_never_asked_does_not_get_examinations():
    """A tenant row predating the flag stores nothing. Nothing means off."""
    assert effective_flags(None)[FEATURE] is False
    assert effective_flags({})[FEATURE] is False
    assert effective_flags({"attendance": False})[FEATURE] is False


def test_every_other_optional_feature_still_defaults_on():
    """The exception is one key, not a change of rule."""
    flags = effective_flags(None)
    for key in OPTIONAL_FEATURES:
        if key in DEFAULT_OFF_FEATURES:
            continue
        assert flags[key] is True, f"{key} lost its default"


def test_a_brand_new_tenant_is_created_with_examinations_off():
    assert default_feature_flags()[FEATURE] is False
    assert default_feature_flags()["attendance"] is True


def test_a_school_that_was_asked_gets_what_it_asked_for():
    assert effective_flags({FEATURE: True})[FEATURE] is True
    assert effective_flags({FEATURE: False})[FEATURE] is False


def test_the_stored_answer_is_what_the_tenant_lookup_reports(db_session, tenant):
    assert is_feature_enabled(tenant.id, FEATURE) is False

    tenant.feature_flags = {FEATURE: True}
    db_session.flush()
    assert is_feature_enabled(tenant.id, FEATURE) is True


# --- the gate, over both transports ----------------------------------------

@pytest.fixture
def officer(db_session, tenant):
    """Somebody who may do everything — so only the flag can refuse them."""
    return _signed_in(db_session, tenant, permissions=ALL_EXAM_PERMISSIONS)


def test_graphql_refuses_when_the_school_does_not_run_examinations(
    client, db_session, tenant, officer, ctx  # noqa: F811
):
    _user, token = officer
    response = _post(client, tenant, token, LIST, {"limit": 10, "offset": 0})

    # Not FORBIDDEN. The officer holds every examination permission there is,
    # so "you may not" would send them to an administrator who cannot help.
    # FEATURE_DISABLED says the module is off, which is a different sentence
    # and a different person to ask.
    assert _errors(response) == ["FEATURE_DISABLED"]


def test_graphql_answers_once_the_school_is_switched_on(
    client, db_session, tenant, officer, ctx  # noqa: F811
):
    tenant.feature_flags = {FEATURE: True}
    db_session.flush()
    _user, token = officer

    response = _post(client, tenant, token, LIST, {"limit": 10, "offset": 0})

    assert _errors(response) == []
    assert response.get_json()["data"]["examinations"]["totalCount"] == 0


def test_the_download_endpoints_close_with_the_same_switch(
    client, db_session, tenant, officer, ctx  # noqa: F811
):
    """A PDF or a spreadsheet is not a second way in.

    These four are REST only because they move a binary. Reaching the module
    through them while the school has it switched off would make the gate
    decorative, and `<id>` is unguessable but not a permission.
    """
    _user, token = officer
    headers = {
        "X-Tenant-Subdomain": tenant.subdomain,
        "Authorization": f"Bearer {token}",
    }
    paper, student, exam = (uuid.uuid4().hex for _ in range(3))
    calls = [
        ("get", f"/api/examinations/papers/{paper}/marks/template", {}),
        ("get", f"/api/examinations/{exam}/students/{student}/marksheet", {}),
        ("post", f"/api/examinations/papers/{paper}/marks/preview", {
            "data": {"file": (BytesIO(b"not really a sheet"), "marks.xlsx")},
            "content_type": "multipart/form-data",
        }),
        ("post", f"/api/examinations/papers/{paper}/marks/import", {
            "data": {"file": (BytesIO(b"not really a sheet"), "marks.xlsx")},
            "content_type": "multipart/form-data",
        }),
    ]

    for method, url, kwargs in calls:
        response = getattr(client, method)(url, headers=headers, **kwargs)
        assert response.status_code == 403, f"{url} answered {response.status_code}"
        assert response.get_json()["error"] == "FeatureDisabled", url


# --- what the super-admin sees ---------------------------------------------

def test_the_panel_offers_examinations_as_a_switch():
    """The user turning this off in production has to be able to find it."""
    from modules.platform.services import list_feature_catalog

    offered = {item["key"]: item for item in list_feature_catalog()}

    assert FEATURE in offered, "the module is gated but the panel cannot reach it"
    assert offered[FEATURE]["toggleable"] is True
    assert offered[FEATURE]["category"] == "optional"
    # Written for somebody who runs schools, not somebody who reads this file.
    assert offered[FEATURE]["label"] != FEATURE
