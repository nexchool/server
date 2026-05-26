"""
Seed default subject templates for the school setup wizard.

Run:
    python -m scripts.seed_subject_templates            # idempotent (skip existing)
    python -m scripts.seed_subject_templates --reseed   # delete+recreate listed boards

All template content is derived from board_subjects.json (sibling file).
Boards: cbse, gseb_english, gseb_gujarati. Languages restricted to
{Gujarati, English, Hindi, Sanskrit}. ICSE / IB are out of scope.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from core.database import db
from modules.school_setup.template_models import SubjectTemplateGroup, SubjectTemplateItem

_BOARD_SUBJECTS_PATH = Path(__file__).resolve().parent / "board_subjects.json"

_NAME_MAX = 100
_CODE_MAX = 20
_STREAM_MAX = 32
_ROLE_MAX = 32
_MEDIUM_MAX = 16
_GROUP_KEY_MAX = 80


def _truncate(value, limit):
    if value is None:
        return None
    s = str(value)
    return s[:limit]


def _row(entry: dict, default_medium: str | None) -> dict:
    """Convert one JSON subject entry into kwargs for SubjectTemplateItem.

    Pick-one groups (`elective_group_key`) are passed through verbatim — the
    apply-template service decides whether to surface them as electives or
    keep all alternatives in the curriculum.
    """
    return {
        "subject_name": _truncate(entry.get("name", "Unknown"), _NAME_MAX),
        "subject_code": _truncate(entry.get("code"), _CODE_MAX),
        "periods_per_week": entry.get("default_periods", 5),
        "is_elective": not entry.get("compulsory", True)
            or "elective" in (entry.get("role") or "").lower(),
        "role": _truncate(entry.get("role"), _ROLE_MAX),
        "medium": _truncate(entry.get("medium") or default_medium, _MEDIUM_MAX),
        "elective_group_key": _truncate(entry.get("elective_group_key"), _GROUP_KEY_MAX),
    }


def _load_templates() -> dict:
    """Read board_subjects.json and shape it for the seeder."""
    with open(_BOARD_SUBJECTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = {}
    for board_code, board in data.get("boards", {}).items():
        display_name = board.get("display_name", board_code.upper())
        default_medium = board.get("default_medium")

        items = []
        for grade_str, grade_data in board.get("standards", {}).items():
            try:
                grade = int(grade_str)
            except (TypeError, ValueError):
                continue

            if "subjects" in grade_data:
                rows = [_row(e, default_medium) for e in grade_data["subjects"]]
                if rows:
                    items.append({"grade": grade, "stream": None, "subjects": rows})

            for stream_key, stream_data in grade_data.get("streams", {}).items():
                stream = _truncate(stream_key, _STREAM_MAX)
                rows = [_row(e, default_medium) for e in stream_data.get("subjects", [])]
                if rows:
                    items.append({"grade": grade, "stream": stream, "subjects": rows})

        result[board_code] = {"name": display_name, "items": items}
    return result


TEMPLATES = _load_templates()


def seed(reseed: bool = False):
    app = create_app()
    with app.app_context():
        seeded = 0
        skipped = 0
        replaced = 0
        for board_code, data in TEMPLATES.items():
            existing = SubjectTemplateGroup.query.filter_by(board_code=board_code).first()
            if existing:
                if not reseed:
                    print(f"  SKIP {board_code} — already exists (id={existing.id})")
                    skipped += 1
                    continue
                db.session.delete(existing)
                db.session.commit()
                print(f"  DROP {board_code} — old group {existing.id} removed")
                replaced += 1

            group = SubjectTemplateGroup(name=data["name"], board_code=board_code)
            db.session.add(group)
            db.session.flush()

            sort_counters = {}
            for row in data["items"]:
                grade = row["grade"]
                stream = row["stream"]
                key = (grade, stream)
                for subj in row["subjects"]:
                    sort_counters[key] = sort_counters.get(key, 0)
                    item = SubjectTemplateItem(
                        template_group_id=group.id,
                        grade_number=grade,
                        stream=stream,
                        sort_order=sort_counters[key],
                        **subj,
                    )
                    sort_counters[key] += 1
                    db.session.add(item)

            db.session.commit()
            item_count = SubjectTemplateItem.query.filter_by(template_group_id=group.id).count()
            print(f"  SEED {board_code} — {item_count} subject items created")
            seeded += 1

        print(f"\nDone: {seeded} seeded, {replaced} replaced, {skipped} skipped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="Delete existing template groups for these board codes and recreate them.",
    )
    args = parser.parse_args()
    seed(reseed=args.reseed)
