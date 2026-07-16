"""Convert a subject-catalogue JSON (subjects per standard per programme)
into the onboarding YAML's `subjects:` + `offerings:` sections.

Usage:
    PYTHONPATH=. python scripts/subject_catalogue_to_yaml.py \
        scripts/schools/subject_catalogue_template.json [-o out.yaml]

The output is a YAML fragment to merge into a school config
(scripts/schools/<subdomain>.yaml). Subjects shared across programmes are
deduplicated by `code`; conflicting definitions for the same code fail fast.

Template: scripts/schools/subject_catalogue_template.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

SUBJECT_FIELDS = ("code", "name", "description", "subject_type", "role", "short_code")
OFFERING_FIELDS = ("code", "weekly", "type", "role", "short_code")


class CatalogueError(ValueError):
    """Invalid or conflicting catalogue input."""


def _clean(entry: Dict[str, Any], allowed: tuple) -> Dict[str, Any]:
    return {k: entry[k] for k in allowed if entry.get(k) not in (None, "")}


def build_sections(catalogue: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Return {"subjects": [...], "offerings": [...]} from a catalogue dict."""
    programmes = catalogue.get("programmes")
    if not isinstance(programmes, list) or not programmes:
        raise CatalogueError("catalogue must contain a non-empty 'programmes' list")

    subjects_by_code: Dict[str, Dict[str, Any]] = {}
    offerings: List[Dict[str, Any]] = []

    for programme in programmes:
        prog_code = (programme.get("code") or "").strip()
        if not prog_code:
            raise CatalogueError("every programme needs a 'code'")

        declared_codes = set()
        for subject in programme.get("catalogue") or []:
            code = str(subject.get("code") or "").strip()
            if not code:
                raise CatalogueError(f"programme {prog_code}: subject without a code")
            if not (subject.get("name") or "").strip():
                raise CatalogueError(f"programme {prog_code}: subject {code} has no name")
            declared_codes.add(code)
            cleaned = _clean(subject, SUBJECT_FIELDS)
            existing = subjects_by_code.get(code)
            if existing is not None and existing != cleaned:
                raise CatalogueError(
                    f"subject code {code} is defined differently in two programmes; "
                    "align the definitions or use distinct codes"
                )
            subjects_by_code[code] = cleaned

        standards = programme.get("standards") or []
        if not standards:
            raise CatalogueError(f"programme {prog_code}: no standards defined")

        for standard in standards:
            grade = str(standard.get("grade") or "").strip()
            if not grade:
                raise CatalogueError(f"programme {prog_code}: standard without a grade")
            rows = standard.get("subjects") or []
            if not rows:
                raise CatalogueError(
                    f"programme {prog_code}, grade {grade}: no subjects listed"
                )
            offering_subjects = []
            for row in rows:
                code = str(row.get("code") or "").strip()
                if code not in declared_codes and code not in subjects_by_code:
                    raise CatalogueError(
                        f"programme {prog_code}, grade {grade}: subject code {code} "
                        "is not declared in any 'catalogue' section"
                    )
                cleaned = _clean(row, OFFERING_FIELDS)
                cleaned.setdefault("weekly", 5)
                cleaned.setdefault("type", "mandatory")
                offering_subjects.append(cleaned)
            offerings.append(
                {"programme": prog_code, "grade": grade, "subjects": offering_subjects}
            )

    subjects = sorted(subjects_by_code.values(), key=lambda s: s["code"])
    return {"subjects": subjects, "offerings": offerings}


def _inline(entry: Dict[str, Any]) -> str:
    """Render one mapping as a single-line YAML flow map, values quoted."""
    parts = []
    for key, value in entry.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parts.append(f"{key}: {value}")
        else:
            escaped = str(value).replace('"', '\\"')
            parts.append(f'{key}: "{escaped}"')
    return "{ " + ", ".join(parts) + " }"


def render_yaml(sections: Dict[str, List[Dict[str, Any]]]) -> str:
    lines = ["subjects:"]
    for subject in sections["subjects"]:
        lines.append(f"  - {_inline(subject)}")
    lines.append("")
    lines.append("offerings:")
    for offering in sections["offerings"]:
        lines.append(f"  - programme: \"{offering['programme']}\"")
        lines.append(f"    grade: \"{offering['grade']}\"")
        lines.append("    subjects:")
        for row in offering["subjects"]:
            lines.append(f"      - {_inline(row)}")
    lines.append("")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", help="path to the subject catalogue JSON")
    parser.add_argument("-o", "--out", help="write YAML here instead of stdout")
    args = parser.parse_args(argv)

    raw = json.loads(Path(args.catalogue).read_text(encoding="utf-8"))
    try:
        sections = build_sections(raw)
    except CatalogueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = render_yaml(sections)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
