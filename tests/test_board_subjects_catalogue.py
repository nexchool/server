"""Content guarantees for scripts/board_subjects.json — the single source of
truth for board curriculum. Pure-Python: reads the JSON file directly.
"""
from __future__ import annotations

from tests.board_subjects_helpers import iter_subject_groups as _iter_subject_groups
from tests.board_subjects_helpers import load_catalogue as _load

GSEB_BOARDS = ("gseb_gujarati", "gseb_english")


def test_physical_education_present_for_std_6_to_10_in_both_gseb_boards():
    boards = _load()["boards"]
    for board in GSEB_BOARDS:
        for standard in range(6, 11):
            subjects = boards[board]["standards"][str(standard)]["subjects"]
            codes = {s["code"] for s in subjects}
            assert "PE" in codes, f"{board} Std {standard} has no PE subject"


def test_physical_education_is_compulsory_with_periods():
    boards = _load()["boards"]
    for board in GSEB_BOARDS:
        for standard in range(6, 11):
            subjects = boards[board]["standards"][str(standard)]["subjects"]
            pe = next(s for s in subjects if s["code"] == "PE")
            assert pe["compulsory"] is True, f"{board} Std {standard}: {pe}"
            assert pe["role"] == "co_curricular", f"{board} Std {standard}: {pe}"
            assert pe["default_periods"] >= 1, f"{board} Std {standard}: {pe}"


def test_every_subject_has_a_code_and_name():
    """Today, board_subjects.json is consumed only by
    scripts/seed_subject_templates.py::_row(), which is defensive (entry.get("code"),
    entry.get("name", "Unknown")) and would silently write "Unknown" rather than
    fail. This test holds the source data itself to a stricter bar: an unnamed or
    codeless subject is a data bug, not something to paper over downstream.
    Planned: Task 4's template resolver will bridge this catalogue into
    seed_service._ensure_subject, which keys on code and would raise KeyError
    without one -- at that point a codeless entry stops being a data-quality nit
    and starts being a hard failure.
    """
    boards = _load()["boards"]
    for board_code, board in boards.items():
        for standard, node in board["standards"].items():
            for subjects in _iter_subject_groups(node):
                for subject in subjects:
                    assert subject.get("code"), f"{board_code} Std {standard}: {subject}"
                    assert subject.get("name"), f"{board_code} Std {standard}: {subject}"


def test_std_1_to_10_roles_are_valid_context_roles():
    """Std 1-10 is what onboarding seeds today, and every role there must be one
    seed_service.VALID_CONTEXT_ROLES accepts, or _validate_config rejects the
    generated offerings."""
    valid = {
        "first_language",
        "second_language",
        "third_language",
        "core",
        "co_curricular",
    }
    boards = _load()["boards"]
    for board_code, board in boards.items():
        for standard, node in board["standards"].items():
            if int(standard) > 10:
                continue
            for subject in node["subjects"]:
                role = subject.get("role")
                if role is not None:
                    assert role in valid, (
                        f"{board_code} Std {standard} {subject['name']}: "
                        f"invalid role '{role}'"
                    )


def test_only_std_11_12_electives_conflate_role_with_type():
    """The senior-secondary streams set role="elective", which is a CONTEXT_TYPE,
    not a CONTEXT_ROLE. The information is not lost -- compulsory: false already
    carries it -- so the catalogue is left alone today. Planned: Task 4's template
    resolver will drop the bogus role rather than pass it through. This test pins
    the blast radius in the meantime: if "elective" ever appears as a role at
    Std 1-10, the resolver's future assumption breaks."""
    boards = _load()["boards"]
    offenders = []
    for board_code, board in boards.items():
        for standard, node in board["standards"].items():
            for subjects in _iter_subject_groups(node):
                for subject in subjects:
                    if subject.get("role") == "elective":
                        offenders.append((board_code, int(standard)))
    assert offenders, "expected the known Std 11-12 elective conflation to exist"
    assert all(standard >= 11 for _, standard in offenders), (
        f"role='elective' leaked below Std 11: "
        f"{sorted({o for o in offenders if o[1] < 11})}"
    )


def test_each_subject_code_maps_to_exactly_one_name():
    """_ensure_subject matches on code alone and returns any existing row without
    updating its name, so two names sharing one code means the name a tenant gets
    depends on which board seeded first. Board-agnostic mnemonics (Task 2b) fix
    this; this test keeps it fixed."""
    boards = _load()["boards"]
    names_by_code: dict[str, set[str]] = {}
    for board_code, board in boards.items():
        for standard, node in board["standards"].items():
            for subjects in _iter_subject_groups(node):
                for subject in subjects:
                    names_by_code.setdefault(subject["code"], set()).add(subject["name"])
    conflicts = {c: sorted(n) for c, n in names_by_code.items() if len(n) > 1}
    assert not conflicts, f"codes with multiple names: {conflicts}"


def test_subject_codes_are_unique_within_each_group():
    """Two entries sharing a code in one standard would silently collapse into a
    single Subject once Task 4's template resolver bridges this catalogue into
    seed_service._ensure_subject, which matches on code alone. Catching it here
    keeps the source data honest in the meantime."""
    boards = _load()["boards"]
    for board_code, board in boards.items():
        for standard, node in board["standards"].items():
            for subjects in _iter_subject_groups(node):
                codes = [s["code"] for s in subjects]
                duplicates = {c for c in codes if codes.count(c) > 1}
                assert not duplicates, (
                    f"{board_code} Std {standard}: duplicate codes {sorted(duplicates)}"
                )
