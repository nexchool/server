"""A subject code is the tenant-wide natural key; a board paper number is not.

These tests pin the separation: `code` is a board-agnostic mnemonic, `exam_code`
carries the board's paper number and may repeat across boards without colliding.
"""
from __future__ import annotations

import re

from tests.board_subjects_helpers import iter_subjects as _all_subjects

# Every board paper number the catalogue carried before codes became
# board-agnostic. Asserting the exact figure is deliberate: the catalogue is
# hand-edited static data, so a drop here is an edit that silently discarded
# board metadata, not incidental drift.
EXPECTED_EXAM_CODES = 160


def test_no_subject_code_is_a_bare_number():
    """Board paper numbers mean different things per board, so they cannot serve
    as a tenant-wide identity key. CBSE 054 is Business Studies; GSEB 054 is
    Physics."""
    offenders = [
        (board, standard, s["code"], s["name"])
        for board, standard, s in _all_subjects()
        if re.fullmatch(r"\d+", s["code"])
    ]
    assert not offenders, f"numeric identity codes remain: {offenders}"


def test_each_subject_name_has_exactly_one_code():
    """Gujarati was GUJ at Std 1-8, 01 at Std 10, 001 at Std 12 and 13 as a second
    language — four Subject rows for one subject."""
    codes_by_name: dict[str, set[str]] = {}
    for _board, _standard, s in _all_subjects():
        codes_by_name.setdefault(s["name"], set()).add(s["code"])
    conflicts = {n: sorted(c) for n, c in codes_by_name.items() if len(c) > 1}
    assert not conflicts, f"names with multiple codes: {conflicts}"


def test_each_subject_code_maps_to_exactly_one_name():
    """The inverse: _ensure_subject matches on code and returns an existing row
    without updating its name, so two names under one code means the name a
    tenant gets depends on which board seeded first."""
    names_by_code: dict[str, set[str]] = {}
    for _board, _standard, s in _all_subjects():
        names_by_code.setdefault(s["code"], set()).add(s["name"])
    conflicts = {c: sorted(n) for c, n in names_by_code.items() if len(n) > 1}
    assert not conflicts, f"codes with multiple names: {conflicts}"


def test_exam_codes_are_preserved_where_the_board_issues_one():
    """The remap must not silently discard board paper numbers — GSEB issues them
    for Std 10 (SSC) and Std 12 (HSC), CBSE for Std 9-12."""
    with_exam = [
        (b, std, s["name"], s["exam_code"])
        for b, std, s in _all_subjects()
        if s.get("exam_code")
    ]
    assert len(with_exam) == EXPECTED_EXAM_CODES, (
        f"expected {EXPECTED_EXAM_CODES} board paper numbers to survive the remap, "
        f"found {len(with_exam)}"
    )
    malformed = [(b, std, n, c) for b, std, n, c in with_exam if not re.fullmatch(r"\d+", c)]
    assert not malformed, f"exam_code must be a bare board number: {malformed}"


def test_exam_codes_may_repeat_across_boards_without_colliding():
    """054 is Business Studies in CBSE and Physics in GSEB. That is fine for an
    exam_code and fatal for a `code` — this test proves the distinction holds."""
    boards_by_exam: dict[str, set[str]] = {}
    for board, _standard, s in _all_subjects():
        if s.get("exam_code"):
            boards_by_exam.setdefault(s["exam_code"], set()).add(board)
    shared = {code: sorted(b) for code, b in boards_by_exam.items() if len(b) > 1}
    assert shared, (
        "expected at least one exam_code shared across boards — 054 is Business "
        "Studies in CBSE and Physics in GSEB, which is exactly why it cannot be "
        "an identity code"
    )


def test_no_subject_is_named_bare_science():
    """CBSE Std 9-10 carried a subject literally named "Science" (paper code 086),
    left behind by Task 2's EVS/SCI rename because it collided on code, not name,
    so the code/name conflict report never surfaced it. It is the same continuing
    subject as "Science and Technology" (Std 6-8 CBSE, Std 6-10 GSEB) — CBSE just
    uses its own board-exam label for the paper. Pinned here so a codeless variant
    of the same gap cannot creep back in."""
    offenders = [
        (board, standard, s["name"])
        for board, standard, s in _all_subjects()
        if s["name"] == "Science"
    ]
    assert not offenders, f"bare 'Science' subject name found: {offenders}"
