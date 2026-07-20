"""Tests for school_setup.template_service. Pure-Python — no Flask, no database.

`build_config_sections` takes any objects with the SubjectTemplateItem
attributes, so tests use SimpleNamespace stubs.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _item(
    grade_number,
    subject_code,
    subject_name,
    periods_per_week=5,
    is_elective=False,
    role=None,
    stream=None,
    sort_order=0,
    exam_code=None,
):
    return SimpleNamespace(
        grade_number=grade_number,
        subject_code=subject_code,
        subject_name=subject_name,
        periods_per_week=periods_per_week,
        is_elective=is_elective,
        role=role,
        stream=stream,
        sort_order=sort_order,
        exam_code=exam_code,
    )


def test_produces_one_subject_entry_per_distinct_code():
    from modules.school_setup.template_service import build_config_sections

    items = [
        _item(1, "GUJ", "Gujarati", role="first_language"),
        _item(2, "GUJ", "Gujarati", role="first_language"),
        _item(2, "MATH", "Mathematics", role="core"),
    ]
    result = build_config_sections(items, "GSEB-GUJ")
    codes = [s["code"] for s in result["subjects"]]
    assert codes == ["GUJ", "MATH"]


def test_subject_entries_carry_name_and_role():
    from modules.school_setup.template_service import build_config_sections

    items = [_item(1, "GUJ", "Gujarati", role="first_language")]
    result = build_config_sections(items, "GSEB-GUJ")
    assert result["subjects"][0] == {
        "code": "GUJ",
        "name": "Gujarati",
        "role": "first_language",
    }


def test_produces_one_offering_per_grade():
    from modules.school_setup.template_service import build_config_sections

    items = [
        _item(1, "GUJ", "Gujarati"),
        _item(1, "MATH", "Mathematics"),
        _item(2, "MATH", "Mathematics"),
    ]
    result = build_config_sections(items, "GSEB-GUJ")
    assert [o["grade"] for o in result["offerings"]] == ["1", "2"]
    assert [s["code"] for s in result["offerings"][0]["subjects"]] == ["GUJ", "MATH"]


def test_maps_periods_per_week_to_weekly():
    from modules.school_setup.template_service import build_config_sections

    items = [_item(1, "GUJ", "Gujarati", periods_per_week=6)]
    result = build_config_sections(items, "GSEB-GUJ")
    assert result["offerings"][0]["subjects"][0]["weekly"] == 6


def test_maps_is_elective_to_offering_type():
    from modules.school_setup.template_service import build_config_sections

    items = [
        _item(9, "SAN", "Sanskrit", is_elective=True),
        _item(9, "MATH", "Mathematics", is_elective=False),
    ]
    result = build_config_sections(items, "GSEB-GUJ")
    types = {s["code"]: s["type"] for s in result["offerings"][0]["subjects"]}
    assert types == {"SAN": "elective", "MATH": "mandatory"}


def test_offering_references_the_given_programme_code():
    from modules.school_setup.template_service import build_config_sections

    items = [_item(1, "GUJ", "Gujarati")]
    result = build_config_sections(items, "GSEB-GUJ")
    assert result["offerings"][0]["programme"] == "GSEB-GUJ"


def test_missing_periods_per_week_falls_back_to_the_seed_default():
    from modules.school_setup.seed_service import DEFAULT_WEEKLY_PERIODS
    from modules.school_setup.template_service import build_config_sections

    items = [_item(1, "GUJ", "Gujarati", periods_per_week=None)]
    result = build_config_sections(items, "GSEB-GUJ")
    assert result["offerings"][0]["subjects"][0]["weekly"] == DEFAULT_WEEKLY_PERIODS


def test_same_code_with_two_different_names_is_rejected():
    from modules.school_setup.template_service import (
        TemplateResolutionError,
        build_config_sections,
    )

    items = [
        _item(1, "SCI", "Science"),
        _item(2, "SCI", "Science and Technology"),
    ]
    with pytest.raises(TemplateResolutionError) as exc:
        build_config_sections(items, "GSEB-GUJ")
    assert "SCI" in str(exc.value)


def test_empty_item_list_produces_empty_sections():
    from modules.school_setup.template_service import build_config_sections

    result = build_config_sections([], "GSEB-GUJ")
    assert result == {"subjects": [], "offerings": []}


def test_grades_are_ordered_numerically_not_lexically():
    from modules.school_setup.template_service import build_config_sections

    items = [_item(10, "MATH", "Mathematics"), _item(2, "MATH", "Mathematics")]
    result = build_config_sections(items, "GSEB-GUJ")
    assert [o["grade"] for o in result["offerings"]] == ["2", "10"]


def test_bogus_elective_role_is_dropped_not_passed_through():
    """board_subjects.json sets role="elective" on 64 Std 11-12 stream entries.
    "elective" is a CONTEXT_TYPE, not a CONTEXT_ROLE — passing it through makes
    _validate_config reject the offerings. is_elective already carries the
    meaning, so the role is dropped.
    """
    from modules.school_setup.template_service import build_config_sections

    items = [_item(11, "ECO", "Economics", is_elective=True, role="elective")]
    result = build_config_sections(items, "GSEB-GUJ")
    assert result["subjects"][0]["role"] is None
    assert result["offerings"][0]["subjects"][0]["type"] == "elective"


def test_valid_roles_are_preserved():
    from modules.school_setup.template_service import build_config_sections

    items = [_item(1, "GUJ", "Gujarati", role="first_language")]
    result = build_config_sections(items, "GSEB-GUJ")
    assert result["subjects"][0]["role"] == "first_language"


def test_resolved_sections_pass_seed_config_validation():
    """The resolver's output must slot into a config that _validate_config accepts."""
    from modules.school_setup.seed_service import _validate_config
    from modules.school_setup.template_service import build_config_sections

    resolved = build_config_sections(
        [
            _item(1, "GUJ", "Gujarati", role="first_language"),
            _item(1, "MATH", "Mathematics", role="core"),
        ],
        "GSEB-GUJ",
    )
    config = {
        "academic_year": {
            "name": "2026-2027",
            "start": "2026-06-01",
            "end": "2027-03-31",
        },
        "units": [{"code": "MN", "name": "Main Campus"}],
        "programmes": [
            {"code": "GSEB-GUJ", "name": "GSEB Gujarati", "board": "GSEB"}
        ],
        "grades": [{"name": "1", "sequence": 1}],
        "subjects": resolved["subjects"],
        "offerings": resolved["offerings"],
        "classes": [
            {"unit": "MN", "programme": "GSEB-GUJ", "grade": "1", "sections": ["A"]}
        ],
    }
    assert _validate_config(config) == []


def test_exam_code_is_carried_onto_the_offering():
    """Task 2b split board paper numbers out of the identity code so they could be
    preserved. Dropping them here would make that split lossy after all."""
    from modules.school_setup.template_service import build_config_sections

    items = [_item(10, "GUJ", "Gujarati", exam_code="01")]
    result = build_config_sections(items, "GSEB-GUJ")
    assert result["offerings"][0]["subjects"][0]["exam_code"] == "01"


def test_exam_code_is_not_hoisted_onto_the_deduplicated_subject():
    """The same subject carries different board numbers at different standards --
    Gujarati is 01 at Std 10 and 001 at Std 12 -- so a single subjects[] entry
    cannot hold it. That is why it lives on the offering."""
    from modules.school_setup.template_service import build_config_sections

    items = [
        _item(10, "GUJ", "Gujarati", exam_code="01"),
        _item(12, "GUJ", "Gujarati", exam_code="001"),
    ]
    result = build_config_sections(items, "GSEB-GUJ")
    assert "exam_code" not in result["subjects"][0]
    by_grade = {o["grade"]: o["subjects"][0]["exam_code"] for o in result["offerings"]}
    assert by_grade == {"10": "01", "12": "001"}
