"""A subject code is the tenant-wide natural key; a board paper number is not.

These tests pin the separation: `code` is a board-agnostic mnemonic, `exam_code`
carries the board's paper number and may repeat across boards without colliding.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
CATALOGUE = SERVER_DIR / "scripts" / "board_subjects.json"


def _load() -> dict:
    with CATALOGUE.open() as fh:
        return json.load(fh)


def _iter_subject_groups(node: dict) -> list[list[dict]]:
    """Std 1-10 nodes keep a flat `subjects` list; Std 11-12 fan out per stream."""
    if "subjects" in node:
        return [node["subjects"]]
    return [s["subjects"] for s in node["streams"].values()]


def _all_subjects():
    for board_code, board in _load()["boards"].items():
        for standard, node in board["standards"].items():
            for subjects in _iter_subject_groups(node):
                for subject in subjects:
                    yield board_code, int(standard), subject


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
    assert len(with_exam) >= 40, (
        f"expected the board paper numbers to survive the remap, found {len(with_exam)}"
    )
    assert all(re.fullmatch(r"\d+", code) for _b, _s, _n, code in with_exam)


def test_exam_codes_may_repeat_across_boards_without_colliding():
    """054 is Business Studies in CBSE and Physics in GSEB. That is fine for an
    exam_code and fatal for a `code` — this test proves the distinction holds."""
    boards_by_exam: dict[str, set[str]] = {}
    for board, _standard, s in _all_subjects():
        if s.get("exam_code"):
            boards_by_exam.setdefault(s["exam_code"], set()).add(board)
    assert any(len(b) > 1 for b in boards_by_exam.values()), (
        "expected at least one exam_code shared across boards"
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
