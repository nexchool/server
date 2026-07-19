"""Content guarantees for scripts/board_subjects.json — the single source of
truth for board curriculum. Pure-Python: reads the JSON file directly.
"""
from __future__ import annotations

import json
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
CATALOGUE = SERVER_DIR / "scripts" / "board_subjects.json"

GSEB_BOARDS = ("gseb_gujarati", "gseb_english")


def _load() -> dict:
    with CATALOGUE.open() as fh:
        return json.load(fh)


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
            assert pe["compulsory"] is True
            assert pe["role"] == "co_curricular"
            assert pe["default_periods"] >= 1


def test_every_subject_has_a_code_and_name():
    """seed_service._ensure_subject keys on code and raises KeyError without one."""
    boards = _load()["boards"]
    for board_code, board in boards.items():
        for standard, node in board["standards"].items():
            groups = (
                [node["subjects"]]
                if "subjects" in node
                else [s["subjects"] for s in node["streams"].values()]
            )
            for subjects in groups:
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
    carries it -- so the catalogue is left alone and the template resolver drops
    the bogus role instead. This test pins the blast radius: if "elective" ever
    appears as a role at Std 1-10, the resolver's assumption breaks."""
    boards = _load()["boards"]
    offenders = []
    for board_code, board in boards.items():
        for standard, node in board["standards"].items():
            groups = (
                [node["subjects"]]
                if "subjects" in node
                else [s["subjects"] for s in node["streams"].values()]
            )
            for subjects in groups:
                for subject in subjects:
                    if subject.get("role") == "elective":
                        offenders.append((board_code, int(standard)))
    assert offenders, "expected the known Std 11-12 elective conflation to exist"
    assert all(standard >= 11 for _, standard in offenders), (
        f"role='elective' leaked below Std 11: "
        f"{sorted({o for o in offenders if o[1] < 11})}"
    )
