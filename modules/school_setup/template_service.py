"""Expand a board subject template into onboarding-config shape.

subject_template_groups / subject_template_items are the single source of truth
for board curriculum (seeded from scripts/board_subjects.json). This module is
the one place where the template's vocabulary is mapped onto the config
vocabulary that seed_service consumes:

    subject_code      -> code
    subject_name      -> name
    periods_per_week  -> weekly
    is_elective       -> type ("elective" | "mandatory")

Keeping that mapping in a single function is the point: the two vocabularies
previously coexisted in two parallel catalogue files that drifted apart.
"""

from __future__ import annotations

from sqlalchemy import or_

from .seed_service import DEFAULT_WEEKLY_PERIODS, VALID_CONTEXT_ROLES
from .template_models import SubjectTemplateGroup, SubjectTemplateItem


class TemplateResolutionError(ValueError):
    """No usable template, or one subject code defined with two different names."""


def _clean_role(role):
    """Drop roles the SubjectContext vocabulary does not accept.

    The Std 11-12 stream entries in board_subjects.json set role="elective",
    which is a CONTEXT_TYPE, not a CONTEXT_ROLE (64 entries across all three
    boards; none below Std 11). Passing it through would make _validate_config
    reject the generated offerings. Nothing is lost by dropping it -- the
    is_elective flag already carries that meaning into the offering's `type`.
    """
    return role if role in VALID_CONTEXT_ROLES else None


def build_config_sections(items, programme_code: str) -> dict:
    """Turn template item rows into the config's `subjects` + `offerings` sections.

    `items` is any iterable of objects carrying the SubjectTemplateItem
    attributes. Ordering of the output follows grade number, then the order in
    which each subject first appears for that grade.
    """
    subjects: dict[str, dict] = {}
    by_grade: dict[int, list[dict]] = {}

    for item in items:
        code = item.subject_code
        if code is None:
            raise TemplateResolutionError(
                f"template item for grade {item.grade_number} "
                f"('{item.subject_name}') has no subject_code"
            )
        name = item.subject_name
        existing = subjects.get(code)
        if existing is None:
            subjects[code] = {"code": code, "name": name, "role": _clean_role(item.role)}
        elif existing["name"] != name:
            raise TemplateResolutionError(
                f"subject code '{code}' is defined twice with different names: "
                f"'{existing['name']}' and '{name}'"
            )

        weekly = item.periods_per_week
        by_grade.setdefault(item.grade_number, []).append(
            {
                "code": code,
                "weekly": DEFAULT_WEEKLY_PERIODS if weekly is None else int(weekly),
                "type": "elective" if item.is_elective else "mandatory",
                "exam_code": item.exam_code,
            }
        )

    offerings = [
        {
            "programme": programme_code,
            "grade": str(grade_number),
            "subjects": by_grade[grade_number],
        }
        for grade_number in sorted(by_grade)
    ]
    return {"subjects": list(subjects.values()), "offerings": offerings}


def resolve_template(
    board_code: str,
    programme_code: str,
    grade_numbers: list[int],
    stream: str | None = None,
) -> dict:
    """Look up a board template and expand it for the given grades.

    `stream` is None for Std 1-10 (items have a NULL stream). For Std 11-12 pass
    the stream name; both stream-specific and stream-agnostic items are included.
    """
    group = (
        SubjectTemplateGroup.query.filter_by(board_code=board_code, is_active=True)
        .first()
    )
    if group is None:
        raise TemplateResolutionError(
            f"no active subject template for board '{board_code}'"
        )

    query = SubjectTemplateItem.query.filter_by(template_group_id=group.id).filter(
        SubjectTemplateItem.grade_number.in_(grade_numbers)
    )
    if stream is None:
        query = query.filter(SubjectTemplateItem.stream.is_(None))
    else:
        query = query.filter(
            or_(
                SubjectTemplateItem.stream.is_(None),
                SubjectTemplateItem.stream == stream,
            )
        )

    items = query.order_by(
        SubjectTemplateItem.grade_number, SubjectTemplateItem.sort_order
    ).all()
    return build_config_sections(items, programme_code)
