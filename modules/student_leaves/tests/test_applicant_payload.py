"""The approver has to be able to tell which child this is.

Shown a leave type, a date range and a reason, a principal who has never met
most of the children in the trust has no way to place the request.
"""

from modules.student_leaves.applicant import build_applicant
from modules.student_leaves.services import create_request
from modules.student_leaves.tests.test_services_state_machine import _sample_payload


def test_applicant_block_identifies_the_child(
    tenant_ctx, student_user, class_with_teacher
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    applicant = build_applicant(leave, include_contact=True)

    assert applicant["student_id"] == student_user.student.id
    assert applicant["display_name"]
    assert applicant["admission_number"]
    assert applicant["class_name"]
    # Present even when the school has not filled them in — the screen renders
    # the absence, rather than the key going missing.
    assert "campus_name" in applicant
    assert "medium_name" in applicant
    assert "profile_picture" in applicant


def test_guardian_contact_is_withheld_from_non_approvers(
    tenant_ctx, student_user, class_with_teacher
):
    """A response handed to every viewer should not carry a parent's phone."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    applicant = build_applicant(leave, include_contact=False)

    assert "guardian_phone" not in applicant
    assert "guardian_name" not in applicant


def test_applicant_uses_the_class_the_leave_was_filed_against(
    tenant_ctx, student_user, class_with_teacher, db_session
):
    """A child moved to another section in March should still show the class
    the January request belongs to."""
    from modules.classes.models import Class

    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    filed_against = build_applicant(leave, include_contact=False)["class_name"]

    moved_to = Class(
        id="c-moved-" + student_user.student.id[-6:],
        tenant_id=leave.tenant_id,
        section="Z",
        academic_year_id=class_with_teacher.academic_year_id,
    )
    db_session.add(moved_to)
    db_session.flush()
    student_user.student.class_id = moved_to.id
    db_session.flush()

    assert build_applicant(leave, include_contact=False)["class_name"] == filed_against


def test_to_dict_gates_contact_on_the_viewer(
    tenant_ctx, student_user, class_with_teacher
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)

    assert "guardian_phone" not in leave.to_dict()["applicant"]

    leave.viewer_may_decide = True
    assert "guardian_phone" in leave.to_dict()["applicant"]
