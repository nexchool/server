"""Who applied — the block an approver needs in order to recognise the child.

A principal deciding a leave has never met most of the children in the trust.
Shown a leave type, a date range and a reason, they have no way to tell which
child this is, so the block below carries the things a school actually uses to
place a student: their name and photo, their class and campus, and the number
to ring if something about the request needs asking about.

Kept out of `services.py`, which is long already and is about the state
machine rather than about presenting a person.
"""

from __future__ import annotations

from typing import Any, Dict

from shared.s3_utils import profile_picture_public_url


def build_applicant(leave, *, include_contact: bool) -> Dict[str, Any]:
    """Identity fields for the student behind ``leave``.

    The class comes from the leave's own ``class_ref``, not the student's
    current class: a child moved to another section in March should still show
    the class the January request was filed against.

    ``include_contact`` adds the guardian's name and phone, which only somebody
    deciding the request has a reason to see. A list response handed to every
    viewer should not carry a parent's phone number.
    """
    student = leave.student
    if student is None:
        return {}

    cls = leave.class_ref
    school_unit = cls.school_unit if cls else None
    medium = cls.medium if cls else None

    applicant: Dict[str, Any] = {
        "student_id": student.id,
        "display_name": student.display_name,
        "admission_number": student.admission_number,
        "roll_number": student.roll_number,
        "class_name": cls.display_name if cls else None,
        "campus_name": school_unit.name if school_unit else None,
        "medium_name": medium.name if medium else None,
        "profile_picture": (
            profile_picture_public_url(student.user.profile_picture_url)
            if student.user
            else None
        ),
    }

    if include_contact:
        # Whichever parent the school holds a number for. The approver is
        # ringing a house, not filling in a form, so one reachable contact
        # beats two empty labelled fields.
        applicant["guardian_name"] = student.father_name or student.mother_name
        applicant["guardian_phone"] = student.father_phone or student.mother_phone

    return applicant
