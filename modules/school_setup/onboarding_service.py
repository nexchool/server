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


# Section prefixes a config uses to put a class in a stream: "Sci-A" is Science
# section A. Mirrors the vocabulary `bulk_generator_service._parse_stream_section`
# resolves against the tenant's `streams` rows; kept as a literal here so
# derivation stays free of the database and testable without one.
STREAM_PREFIXES = {
    "sci": "Science",
    "science": "Science",
    "com": "Commerce",
    "commerce": "Commerce",
    "art": "Arts",
    "arts": "Arts",
    "voc": "Vocational",
    "vocational": "Vocational",
}


def _streams_wanted(config: dict) -> dict[tuple[str, str], set[str]]:
    """Which streams each (programme, grade) actually runs, per its classes.

    Read from the config rather than from the template on purpose. A board
    prescribes four streams; a school runs the ones it runs, and deriving the
    other two would leave offerings behind that no class will ever use.
    """
    wanted: dict[tuple[str, str], set[str]] = {}
    for cl in config.get("classes", []):
        for raw_section in cl.get("sections", []):
            prefix, _, rest = str(raw_section).partition("-")
            if not rest:
                continue
            stream = STREAM_PREFIXES.get(prefix.strip().lower())
            if stream is None:
                continue
            key = (cl["programme"], str(cl["grade"]))
            wanted.setdefault(key, set()).add(stream)
    return wanted


def _resolve_extra_subjects(config, subjects_by_code, offerings_by_key):
    """Append off-catalogue subjects, or extend a template subject to a grade
    the template does not cover.

    The rule is same-code-*different-name* is rejected, same-code-*same-name*
    is reused: a code mapping to two names is the two-catalogues drift this
    whole plan exists to remove, but a code mapping to the grades it's
    actually taught at is just... a subject taught at more grades. `PE` at
    Nursery is the same Physical Education as `PE` at Std 6, not a collision.

    May also originate an offering the template has none for: pre-primary
    (Nursery/LKG/UKG) has no board syllabus anywhere in India, so those grades
    get their entire curriculum from here rather than from resolve_template.
    """
    grade_names = {str(g["name"]) for g in config.get("grades", [])}
    for extra in config.get("extra_subjects", []):
        code = extra["code"]
        existing = subjects_by_code.get(code)
        if existing is not None:
            if existing["name"] != extra["name"]:
                raise DerivationError(
                    f"extra subject '{code}' collides with an existing subject "
                    f"of the same code but a different name: "
                    f"'{existing['name']}' vs '{extra['name']}'"
                )
            # Same code, same name: this is the same subject taught at another
            # grade, not a redefinition. Reuse the existing entry as-is.
        else:
            subjects_by_code[code] = {
                "code": code,
                "name": extra["name"],
                "role": extra.get("role"),
            }
        try:
            weekly = int(extra.get("weekly", 1))
        except (TypeError, ValueError) as e:
            raise DerivationError(
                f"extra subject '{code}' has an invalid 'weekly' value "
                f"'{extra.get('weekly')}': {e}"
            ) from e
        for grade in extra["grades"]:
            grade_str = str(grade)
            if grade_str not in grade_names:
                raise DerivationError(
                    f"extra subject '{code}' targets grade '{grade_str}', which "
                    f"is not declared in this config's grades"
                )
            line = {
                "code": code,
                "weekly": weekly,
                "type": extra.get("type", "elective"),
                "exam_code": None,
            }
            # An extra subject names no stream, so it belongs to every stream
            # this (programme, grade) runs — appended to each of them, or to a
            # freshly originated stream-agnostic offering if the board template
            # had nothing for this (programme, grade) at all.
            targets = [
                k
                for k in offerings_by_key
                if k[0] == extra["programme"] and k[1] == grade_str
            ]
            if not targets:
                key = (extra["programme"], grade_str, None)
                offerings_by_key[key] = {
                    "programme": extra["programme"],
                    "grade": grade_str,
                    "subjects": [],
                }
                targets = [key]
            for key in targets:
                offerings_by_key[key]["subjects"].append(dict(line))


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
    # Only grades the board actually prescribes go to the template. Pre-primary
    # (Nursery/LKG/UKG) has no board syllabus anywhere in India, so a non-numeric
    # grade name is normal, not an error -- those grades get their curriculum
    # from extra_subjects instead.
    grade_numbers = sorted(
        {int(g["name"]) for g in derived.get("grades", []) if str(g["name"]).isdigit()}
    )

    subjects_by_code: dict[str, dict] = {}
    # Keyed by (programme, grade, stream). A stream of None is the offering
    # every stream at that grade shares, and the only key a school without
    # streams ever produces.
    offerings_by_key: dict[tuple[str, str, str | None], dict] = {}
    streams_wanted = _streams_wanted(derived)

    def _absorb(resolved: dict, stream: str | None) -> None:
        for subject in resolved["subjects"]:
            subjects_by_code.setdefault(subject["code"], subject)
        for offering in resolved["offerings"]:
            key = (offering["programme"], str(offering["grade"]), stream)
            if stream is not None:
                offering = {**offering, "stream": stream}
            offerings_by_key[key] = offering

    for programme in derived.get("programmes", []):
        board_code = programme.get("template_board_code")
        if not board_code:
            raise DerivationError(
                f"programme '{programme['code']}' has no template_board_code, so "
                f"its curriculum cannot be derived"
            )

        # Grades this programme runs streams at are resolved once per stream;
        # the rest keep the single stream-agnostic resolution.
        streamed_grades = {
            grade: streams
            for (prog_code, grade), streams in streams_wanted.items()
            if prog_code == programme["code"]
        }
        plain_grades = [
            g for g in grade_numbers if str(g) not in streamed_grades
        ]

        def _resolve(grades: list[int], stream: str | None):
            if not grades:
                return None
            try:
                return resolver(board_code, programme["code"], grades, stream)
            except ValueError as e:
                where = f" for stream '{stream}'" if stream else ""
                raise DerivationError(
                    f"could not resolve template for programme "
                    f"'{programme['code']}' (board '{board_code}'){where}: {e}"
                ) from e

        resolved = _resolve(plain_grades, None)
        if resolved is not None:
            _absorb(resolved, None)

        for grade, streams in streamed_grades.items():
            if not str(grade).isdigit():
                # Pre-primary sections can carry a hyphen without naming a
                # stream; those grades have no template to resolve anyway.
                continue
            for stream in sorted(streams):
                resolved = _resolve([int(grade)], stream)
                if resolved is not None:
                    _absorb(resolved, stream)

    _resolve_extra_subjects(derived, subjects_by_code, offerings_by_key)

    derived["subjects"] = list(subjects_by_code.values())
    derived["offerings"] = list(offerings_by_key.values())
    return derived
