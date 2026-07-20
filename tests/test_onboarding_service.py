"""The orchestrator derives subjects/offerings, then hands a complete config to
seed_school. Pure-Python: the resolver is injected, so no database is needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _config(**overrides):
    base = {
        "academic_year": {
            "name": "2026-2027",
            "start": "2026-06-01",
            "end": "2027-03-31",
        },
        "units": [{"code": "MN", "name": "Main Campus"}],
        "programmes": [
            {
                "code": "GSEB-GUJ",
                "name": "GSEB Gujarati",
                "board": "GSEB",
                "template_board_code": "gseb_gujarati",
            }
        ],
        "grades": [{"name": "1", "sequence": 1}, {"name": "2", "sequence": 2}],
        "classes": [
            {"unit": "MN", "programme": "GSEB-GUJ", "grade": "1", "sections": ["A"]}
        ],
    }
    base.update(overrides)
    return base


def _fake_resolver(board_code, programme_code, grades, stream=None):
    return {
        "subjects": [{"code": "GUJ", "name": "Gujarati", "role": "first_language"}],
        "offerings": [
            {
                "programme": programme_code,
                "grade": str(g),
                "subjects": [
                    {"code": "GUJ", "weekly": 6, "type": "mandatory", "exam_code": None}
                ],
            }
            for g in grades
        ],
    }


def test_derives_subjects_and_offerings_from_the_programme_template():
    from modules.school_setup.onboarding_service import derive_config

    result = derive_config(_config(), resolver=_fake_resolver)
    assert [s["code"] for s in result["subjects"]] == ["GUJ"]
    assert [o["grade"] for o in result["offerings"]] == ["1", "2"]


def test_supplied_subjects_are_rejected_rather_than_merged():
    """The contract no longer accepts declared subjects. Silently dropping them
    would hide a stale draft or a hand-edited YAML; rejecting surfaces it."""
    from modules.school_setup.onboarding_service import (
        DerivationError,
        derive_config,
    )

    with pytest.raises(DerivationError) as exc:
        derive_config(_config(subjects=[{"code": "X", "name": "X"}]), resolver=_fake_resolver)
    assert "subjects" in str(exc.value)


def test_supplied_offerings_are_rejected():
    from modules.school_setup.onboarding_service import (
        DerivationError,
        derive_config,
    )

    with pytest.raises(DerivationError):
        derive_config(
            _config(offerings=[{"programme": "GSEB-GUJ", "grade": "1", "subjects": []}]),
            resolver=_fake_resolver,
        )


def test_programme_without_a_template_is_rejected():
    from modules.school_setup.onboarding_service import (
        DerivationError,
        derive_config,
    )

    cfg = _config()
    del cfg["programmes"][0]["template_board_code"]
    with pytest.raises(DerivationError) as exc:
        derive_config(cfg, resolver=_fake_resolver)
    assert "GSEB-GUJ" in str(exc.value)


def test_extra_subjects_are_appended_and_marked():
    """The one escape hatch: a school teaching something off-catalogue. Additive
    only -- it can never replace or shadow a template subject."""
    from modules.school_setup.onboarding_service import derive_config

    cfg = _config(
        extra_subjects=[
            {
                "code": "ROBO",
                "name": "Robotics",
                "grades": ["2"],
                "programme": "GSEB-GUJ",
                "weekly": 2,
            }
        ]
    )
    result = derive_config(cfg, resolver=_fake_resolver)
    assert "ROBO" in [s["code"] for s in result["subjects"]]
    grade2 = next(o for o in result["offerings"] if o["grade"] == "2")
    assert "ROBO" in [s["code"] for s in grade2["subjects"]]
    grade1 = next(o for o in result["offerings"] if o["grade"] == "1")
    assert "ROBO" not in [s["code"] for s in grade1["subjects"]]


def test_extra_subject_colliding_with_a_template_code_is_rejected():
    from modules.school_setup.onboarding_service import (
        DerivationError,
        derive_config,
    )

    cfg = _config(
        extra_subjects=[
            {"code": "GUJ", "name": "Something Else", "grades": ["1"], "programme": "GSEB-GUJ"}
        ]
    )
    with pytest.raises(DerivationError) as exc:
        derive_config(cfg, resolver=_fake_resolver)
    assert "GUJ" in str(exc.value)


def test_multiple_programmes_each_resolve_their_own_template():
    from modules.school_setup.onboarding_service import derive_config

    cfg = _config(
        programmes=[
            {
                "code": "GSEB-GUJ",
                "name": "GSEB Gujarati",
                "board": "GSEB",
                "template_board_code": "gseb_gujarati",
            },
            {
                "code": "GSEB-ENG",
                "name": "GSEB English",
                "board": "GSEB",
                "template_board_code": "gseb_english",
            },
        ]
    )
    result = derive_config(cfg, resolver=_fake_resolver)
    assert {o["programme"] for o in result["offerings"]} == {"GSEB-GUJ", "GSEB-ENG"}


def test_the_original_config_is_not_mutated():
    from modules.school_setup.onboarding_service import derive_config

    cfg = _config()
    derive_config(cfg, resolver=_fake_resolver)
    assert "subjects" not in cfg
    assert "offerings" not in cfg
