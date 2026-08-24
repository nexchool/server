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


def test_derived_config_passes_seed_validation():
    """The orchestrator's output is what _validate_config sees, so it must be
    accepted -- otherwise every onboarding fails at the preview step."""
    from modules.school_setup.onboarding_service import derive_config
    from modules.school_setup.seed_service import _validate_config

    derived = derive_config(_config(), resolver=_fake_resolver)
    assert _validate_config(derived) == []


# --- pre-primary grades: no board syllabus, so extra_subjects is the only ---
# --- source of curriculum for them (Nursery/LKG/UKG have no template row). --


def test_non_numeric_grade_is_excluded_from_template_resolution():
    """Nursery has no board syllabus anywhere in India, so it must not reach
    the resolver, and its absence from grade_numbers must not raise."""
    from modules.school_setup.onboarding_service import derive_config

    cfg = _config(
        grades=[{"name": "Nursery", "sequence": 1}, {"name": "1", "sequence": 2}]
    )
    result = derive_config(cfg, resolver=_fake_resolver)
    # Only "1" reaches the template; Nursery gets no offering from it.
    assert [o["grade"] for o in result["offerings"]] == ["1"]


def test_extra_subjects_originate_an_offering_for_a_grade_the_template_has_none_for():
    """Pre-primary is the school's own invented curriculum, not the board's --
    extra_subjects is the only way such a grade gets any curriculum at all."""
    from modules.school_setup.onboarding_service import derive_config

    cfg = _config(
        grades=[{"name": "Nursery", "sequence": 1}, {"name": "1", "sequence": 2}],
        extra_subjects=[
            {
                "code": "NUR-GUJ",
                "name": "Gujarati (Nursery)",
                "grades": ["Nursery"],
                "programme": "GSEB-GUJ",
                "weekly": 6,
            }
        ],
    )
    result = derive_config(cfg, resolver=_fake_resolver)
    nursery = next(o for o in result["offerings"] if o["grade"] == "Nursery")
    assert [s["code"] for s in nursery["subjects"]] == ["NUR-GUJ"]


def test_extra_subject_targeting_an_undeclared_grade_is_rejected():
    """A typo in extra_subjects[].grades must not silently originate an
    offering for a grade that was never declared in this config's grades."""
    from modules.school_setup.onboarding_service import (
        DerivationError,
        derive_config,
    )

    cfg = _config(
        extra_subjects=[
            {
                "code": "ROBO",
                "name": "Robotics",
                "grades": ["99"],
                "programme": "GSEB-GUJ",
            }
        ]
    )
    with pytest.raises(DerivationError) as exc:
        derive_config(cfg, resolver=_fake_resolver)
    assert "ROBO" in str(exc.value)
    assert "99" in str(exc.value)


def test_extra_subject_same_code_and_name_as_template_extends_it_to_a_new_grade():
    """Same code + same name is the same subject taught at another grade, not
    a redefinition -- PE at Nursery is the same Physical Education as PE at
    Std 6, not a collision. It must be reused, not rejected."""
    from modules.school_setup.onboarding_service import derive_config

    cfg = _config(
        grades=[
            {"name": "Nursery", "sequence": 1},
            {"name": "1", "sequence": 2},
            {"name": "2", "sequence": 3},
        ],
        extra_subjects=[
            {
                "code": "GUJ",
                "name": "Gujarati",  # matches the template subject's name exactly
                "grades": ["Nursery"],
                "programme": "GSEB-GUJ",
                "weekly": 6,
            }
        ],
    )
    result = derive_config(cfg, resolver=_fake_resolver)

    nursery = next(o for o in result["offerings"] if o["grade"] == "Nursery")
    assert [s["code"] for s in nursery["subjects"]] == ["GUJ"]
    # The template's own grades are unaffected by the extension.
    grade1 = next(o for o in result["offerings"] if o["grade"] == "1")
    assert [s["code"] for s in grade1["subjects"]] == ["GUJ"]


def test_extra_subject_same_code_different_name_is_still_rejected():
    """Same code, different name IS the real collision -- a code mapping to
    two names is the two-catalogues drift this plan exists to remove."""
    from modules.school_setup.onboarding_service import (
        DerivationError,
        derive_config,
    )

    cfg = _config(
        grades=[{"name": "Nursery", "sequence": 1}, {"name": "1", "sequence": 2}],
        extra_subjects=[
            {
                "code": "GUJ",
                "name": "Something Else",
                "grades": ["Nursery"],
                "programme": "GSEB-GUJ",
            }
        ],
    )
    with pytest.raises(DerivationError) as exc:
        derive_config(cfg, resolver=_fake_resolver)
    assert "Gujarati" in str(exc.value)
    assert "Something Else" in str(exc.value)


def test_extended_subject_appears_exactly_once_in_the_subjects_list():
    """The extension path must reuse the existing subjects_by_code entry, not
    add a second one -- one code must map to exactly one subjects[] row."""
    from modules.school_setup.onboarding_service import derive_config

    cfg = _config(
        grades=[
            {"name": "Nursery", "sequence": 1},
            {"name": "1", "sequence": 2},
            {"name": "2", "sequence": 3},
        ],
        extra_subjects=[
            {
                "code": "GUJ",
                "name": "Gujarati",
                "grades": ["Nursery"],
                "programme": "GSEB-GUJ",
                "weekly": 6,
            }
        ],
    )
    result = derive_config(cfg, resolver=_fake_resolver)
    assert [s["code"] for s in result["subjects"]].count("GUJ") == 1


# --------------------------------------------------------------------------- #
# Streams
#
# A board prescribes a different curriculum per stream at Std 11-12. The
# resolver has always accepted a stream; until migration 119 nothing passed one,
# so Science and Commerce derived the same subjects and the schema could not
# have held them apart anyway.
# --------------------------------------------------------------------------- #

def _streamed_resolver(board_code, programme_code, grades, stream=None):
    """Std 11 by stream: everyone takes English, only Science takes Physics,
    and Mathematics is taken by Science and Commerce but not Arts."""
    per_stream = {
        "Science": ["ENG", "MATH", "PHY"],
        "Commerce": ["ENG", "MATH", "ACC"],
        "Arts": ["ENG", "HIST"],
        None: ["ENG"],
    }
    codes = per_stream[stream]
    return {
        "subjects": [{"code": c, "name": c.title(), "role": None} for c in codes],
        "offerings": [
            {
                "programme": programme_code,
                "grade": str(g),
                "subjects": [
                    {"code": c, "weekly": 4, "type": "mandatory", "exam_code": None}
                    for c in codes
                ],
            }
            for g in grades
        ],
    }


def _streamed_config():
    return _config(
        grades=[{"name": "11", "sequence": 11}],
        classes=[
            {"unit": "MN", "programme": "GSEB-GUJ", "grade": "11",
             "sections": ["Sci-A", "Com-A", "Arts-A"]}
        ],
    )


def test_each_stream_at_a_grade_derives_its_own_curriculum():
    from modules.school_setup.onboarding_service import derive_config

    result = derive_config(_streamed_config(), resolver=_streamed_resolver)

    by_stream = {o.get("stream"): {s["code"] for s in o["subjects"]}
                 for o in result["offerings"]}
    assert by_stream["Science"] == {"ENG", "MATH", "PHY"}
    assert by_stream["Commerce"] == {"ENG", "MATH", "ACC"}
    assert by_stream["Arts"] == {"ENG", "HIST"}


def test_a_subject_two_streams_share_is_offered_to_each_of_them():
    """Mathematics at Std 11 is one subject and two offerings. Collapsing it to
    one is what put Mathematics in front of an Arts section."""
    from modules.school_setup.onboarding_service import derive_config

    result = derive_config(_streamed_config(), resolver=_streamed_resolver)

    maths = [o.get("stream") for o in result["offerings"]
             if any(s["code"] == "MATH" for s in o["subjects"])]
    assert sorted(maths) == ["Commerce", "Science"]
    assert len([s for s in result["subjects"] if s["code"] == "MATH"]) == 1


def test_a_school_running_no_streams_derives_exactly_one_offering_per_grade():
    """The stream-agnostic path is the one every primary school takes."""
    from modules.school_setup.onboarding_service import derive_config

    result = derive_config(_config(), resolver=_fake_resolver)

    assert all(o.get("stream") is None for o in result["offerings"])
    assert sorted(o["grade"] for o in result["offerings"]) == ["1", "2"]


def test_only_the_streams_the_school_actually_runs_are_derived():
    """The board prescribes four tracks; a school that opens two gets two."""
    from modules.school_setup.onboarding_service import derive_config

    config = _config(
        grades=[{"name": "11", "sequence": 11}],
        classes=[
            {"unit": "MN", "programme": "GSEB-GUJ", "grade": "11",
             "sections": ["Sci-A", "Com-A"]}
        ],
    )

    result = derive_config(config, resolver=_streamed_resolver)

    assert {o.get("stream") for o in result["offerings"]} == {"Science", "Commerce"}


def test_an_extra_subject_reaches_every_stream_at_its_grade():
    """An off-catalogue subject names no stream, so it is taught to all of them."""
    from modules.school_setup.onboarding_service import derive_config

    config = _streamed_config()
    config["extra_subjects"] = [
        {"code": "YOGA", "name": "Yoga", "programme": "GSEB-GUJ",
         "grades": ["11"], "weekly": 1, "type": "mandatory"}
    ]

    result = derive_config(config, resolver=_streamed_resolver)

    carrying = {o.get("stream") for o in result["offerings"]
                if any(s["code"] == "YOGA" for s in o["subjects"])}
    assert carrying == {"Science", "Commerce", "Arts"}
