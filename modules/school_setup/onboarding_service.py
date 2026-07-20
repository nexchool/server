"""Derive a complete onboarding config from board templates, then seed it.

This module is the only place resolution and seeding meet. It sits ABOVE both:
template_service imports constants from seed_service, so seed_service must never
import template_service -- the cycle would be immediate.

Why derivation rather than declaration: subjects and offerings used to be
supplied by the caller, which meant a hand-edited YAML and a stale panel draft
could each state a different curriculum from the board template. Removing the
ability to declare removes the drift, rather than correcting each instance.
"""

from __future__ import annotations

import copy

from .template_service import resolve_template


class DerivationError(ValueError):
    """The config declares what it must derive, or names a template it cannot use."""


def _resolve_extra_subjects(config, subjects_by_code, offerings_by_key):
    """Append off-catalogue subjects. Additive only -- never shadows a template
    subject, and only lands on the (programme, grade) pairs it names.
    """
    for extra in config.get("extra_subjects", []):
        code = extra["code"]
        if code in subjects_by_code:
            raise DerivationError(
                f"extra subject '{code}' collides with a template subject of the "
                f"same code; pick a distinct code"
            )
        subjects_by_code[code] = {
            "code": code,
            "name": extra["name"],
            "role": extra.get("role"),
        }
        for grade in extra["grades"]:
            key = (extra["programme"], str(grade))
            if key not in offerings_by_key:
                raise DerivationError(
                    f"extra subject '{code}' targets (programme "
                    f"{extra['programme']}, grade {grade}), which has no offering"
                )
            offerings_by_key[key]["subjects"].append(
                {
                    "code": code,
                    "weekly": int(extra.get("weekly", 1)),
                    "type": extra.get("type", "elective"),
                    "exam_code": None,
                }
            )


def derive_config(config: dict, resolver=resolve_template) -> dict:
    """Return a copy of `config` with `subjects` and `offerings` filled in.

    `resolver` is injected so the derivation logic is testable without a
    database. Callers use the default.
    """
    for field in ("subjects", "offerings"):
        if config.get(field):
            raise DerivationError(
                f"config must not declare '{field}' -- it is derived from each "
                f"programme's board template. A config carrying it is either a "
                f"stale draft or a hand-edited file."
            )

    derived = copy.deepcopy(config)
    grade_numbers = sorted({int(g["name"]) for g in derived.get("grades", [])})

    subjects_by_code: dict[str, dict] = {}
    offerings_by_key: dict[tuple[str, str], dict] = {}

    for programme in derived.get("programmes", []):
        board_code = programme.get("template_board_code")
        if not board_code:
            raise DerivationError(
                f"programme '{programme['code']}' has no template_board_code, so "
                f"its curriculum cannot be derived"
            )
        resolved = resolver(board_code, programme["code"], grade_numbers)
        for subject in resolved["subjects"]:
            subjects_by_code.setdefault(subject["code"], subject)
        for offering in resolved["offerings"]:
            offerings_by_key[(offering["programme"], offering["grade"])] = offering

    _resolve_extra_subjects(derived, subjects_by_code, offerings_by_key)

    derived["subjects"] = list(subjects_by_code.values())
    derived["offerings"] = list(offerings_by_key.values())
    return derived
