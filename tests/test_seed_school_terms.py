"""Validation rules for the config's `terms` section. Pure-Python — no database."""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _config_with_terms(terms) -> dict:
    return {
        "academic_year": {
            "name": "2026-2027",
            "start": "2026-06-01",
            "end": "2027-03-31",
        },
        "units": [{"code": "MN", "name": "Main Campus"}],
        "programmes": [{"code": "P1", "name": "GSEB", "board": "GSEB"}],
        "grades": [{"name": "1", "sequence": 1}],
        "subjects": [{"code": "MATH", "name": "Mathematics"}],
        "offerings": [
            {"programme": "P1", "grade": "1", "subjects": [{"code": "MATH", "weekly": 6}]}
        ],
        "classes": [{"unit": "MN", "programme": "P1", "grade": "1", "sections": ["A"]}],
        "terms": terms,
    }


def test_terms_are_optional():
    from modules.school_setup.seed_service import _validate_config

    config = _config_with_terms([])
    assert _validate_config(config) == []


def test_valid_terms_pass():
    from modules.school_setup.seed_service import _validate_config

    config = _config_with_terms(
        [
            {"name": "Term 1", "sequence": 1, "start": "2026-06-01", "end": "2026-10-31"},
            {"name": "Term 2", "sequence": 2, "start": "2026-11-01", "end": "2027-03-31"},
        ]
    )
    assert _validate_config(config) == []


def test_term_starting_after_it_ends_is_rejected():
    from modules.school_setup.seed_service import _validate_config

    config = _config_with_terms(
        [{"name": "Term 1", "start": "2026-10-31", "end": "2026-06-01"}]
    )
    errors = _validate_config(config)
    assert any("starts after it ends" in e for e in errors)


def test_term_outside_the_academic_year_is_rejected():
    from modules.school_setup.seed_service import _validate_config

    config = _config_with_terms(
        [{"name": "Term 1", "start": "2026-01-01", "end": "2026-05-01"}]
    )
    errors = _validate_config(config)
    assert any("outside the academic year" in e for e in errors)


def test_duplicate_term_names_are_rejected():
    from modules.school_setup.seed_service import _validate_config

    config = _config_with_terms(
        [
            {"name": "Term 1", "start": "2026-06-01", "end": "2026-10-31"},
            {"name": "Term 1", "start": "2026-11-01", "end": "2027-03-31"},
        ]
    )
    errors = _validate_config(config)
    assert any("duplicate term name" in e for e in errors)


def test_overlapping_terms_are_rejected():
    from modules.school_setup.seed_service import _validate_config

    config = _config_with_terms(
        [
            {"name": "Term 1", "start": "2026-06-01", "end": "2026-11-30"},
            {"name": "Term 2", "start": "2026-11-01", "end": "2027-03-31"},
        ]
    )
    errors = _validate_config(config)
    assert any("overlap" in e for e in errors)


def test_term_with_unparseable_dates_is_rejected_without_raising():
    from modules.school_setup.seed_service import _validate_config

    config = _config_with_terms([{"name": "Term 1", "start": "not-a-date", "end": None}])
    errors = _validate_config(config)
    assert any("invalid start/end dates" in e for e in errors)


def test_duplicate_term_codes_are_rejected():
    """academic_terms also carries uq_academic_terms_year_code — two terms with
    different names but the same code pass _ensure_term's name-scoped lookup
    and blow up on the second flush's IntegrityError unless caught here."""
    from modules.school_setup.seed_service import _validate_config

    config = _config_with_terms(
        [
            {"name": "Term 1", "code": "T1", "start": "2026-06-01", "end": "2026-10-31"},
            {"name": "Term 2", "code": "T1", "start": "2026-11-01", "end": "2027-03-31"},
        ]
    )
    errors = _validate_config(config)
    assert any("duplicate term code" in e for e in errors)


def test_terms_that_both_omit_code_validate_cleanly():
    """uq_academic_terms_year_code only enforces uniqueness WHERE code IS NOT
    NULL, so two term rows both omitting a code are legal."""
    from modules.school_setup.seed_service import _validate_config

    config = _config_with_terms(
        [
            {"name": "Term 1", "start": "2026-06-01", "end": "2026-10-31"},
            {"name": "Term 2", "start": "2026-11-01", "end": "2027-03-31"},
        ]
    )
    assert _validate_config(config) == []
