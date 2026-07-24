"""
Academic Calendar Import

Bulk-load public holidays, vacations, examination windows or school events from
a CSV that follows the downloadable template. Each row is validated through the
same create services used by the wizard (so overlap/duplicate rules apply), but
silently — one summary audit entry + notification is emitted for the whole
import instead of one per row. Valid rows are saved; invalid rows are skipped
and reported with their line number.
"""

from datetime import date
from io import StringIO
import csv

from flask import g

from . import activity, holiday_services, services

IMPORT_TYPES = ("public_holidays", "vacations", "exam_windows", "events")

# Columns emitted in the template (order matters); trailing ones are optional.
TEMPLATE_COLUMNS = {
    "public_holidays": ["name", "holiday_type", "start_date", "end_date", "applies_to", "description"],
    "vacations": ["name", "start_date", "end_date", "description"],
    "exam_windows": ["name", "exam_type", "start_date", "end_date", "description"],
    "events": ["name", "event_type", "event_date", "applies_to", "description"],
}

# Columns a row MUST provide a value for.
REQUIRED_COLUMNS = {
    "public_holidays": ["name", "start_date"],
    "vacations": ["name", "start_date", "end_date"],
    "exam_windows": ["name", "start_date", "end_date"],
    "events": ["name", "event_date"],
}

_SAMPLE_ROW = {
    "public_holidays": ["Independence Day", "national", "2026-08-15", "", "entire_school", "National holiday"],
    "vacations": ["Diwali Break", "2026-10-20", "2026-10-31", "Festival vacation"],
    "exam_windows": ["Mid Term", "mid_term", "2026-09-14", "2026-09-20", "Half-yearly exams"],
    "events": ["Sports Day", "activity", "2026-12-05", "entire_school", "Annual sports meet"],
}

_LABEL = {
    "public_holidays": "public holidays",
    "vacations": "vacations",
    "exam_windows": "examination windows",
    "events": "school events",
}


class ImportValidationError(Exception):
    """Raised when the file/type itself is unusable (bad type, missing columns)."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


def import_template_csv(import_type: str) -> bytes:
    if import_type not in IMPORT_TYPES:
        raise ImportValidationError(
            f"Unsupported import type '{import_type}'. Use one of: {', '.join(IMPORT_TYPES)}"
        )
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(TEMPLATE_COLUMNS[import_type])
    writer.writerow(_SAMPLE_ROW[import_type])
    return buf.getvalue().encode("utf-8-sig")


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat((value or "").strip())
        return True
    except (ValueError, TypeError):
        return False


def _clean(row: dict, key: str) -> str:
    return (row.get(key) or "").strip()


def _row_errors_from_result(result: dict, line: int) -> list[dict]:
    """Flatten a create_holiday failure dict into per-field error entries."""
    details = result.get("details")
    if isinstance(details, dict) and details:
        return [{"row": line, "field": f, "message": m} for f, m in details.items()]
    return [{"row": line, "field": "row", "message": result.get("error", "Invalid row.")}]


def import_rows(cal, import_type: str, file_text: str) -> dict:
    """Validate + insert rows from `file_text`; return an import summary."""
    if import_type not in IMPORT_TYPES:
        raise ImportValidationError(
            f"Unsupported import type '{import_type}'. Use one of: {', '.join(IMPORT_TYPES)}"
        )

    reader = csv.DictReader(StringIO(file_text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS[import_type] if c not in header]
    if missing:
        raise ImportValidationError(
            f"Template is missing required column(s): {', '.join(missing)}.",
            {"expected_columns": TEMPLATE_COLUMNS[import_type]},
        )

    year_id = cal.academic_year_id
    errors: list[dict] = []
    imported = 0
    total = 0

    for offset, row in enumerate(reader):
        line = offset + 2  # header is line 1
        # Skip fully-blank lines.
        if not any((v or "").strip() for v in row.values()):
            continue
        total += 1

        row_errs = _import_one(import_type, year_id, row, line)
        if row_errs:
            errors.extend(row_errs)
        else:
            imported += 1

    if imported:
        year_name = cal.academic_year.name if cal.academic_year else year_id
        activity.audit_calendar_action(
            "import_completed", "academic_calendar", cal.id,
            f"Imported {imported} {_LABEL[import_type]} into {year_name}",
            g.tenant_id,
            academic_year_id=cal.academic_year_id,
            meta={"import_type": import_type, "imported": imported, "skipped": len(errors)},
        )
        activity.notify_calendar_change(
            "Academic calendar updated",
            f"{imported} {_LABEL[import_type]} were imported.",
            g.tenant_id,
            {"academic_year_id": year_id},
        )

    return {
        "import_type": import_type,
        "total": total,
        "imported": imported,
        "skipped": len(errors),
        "errors": errors,
    }


def _import_one(import_type: str, year_id: str, row: dict, line: int) -> list[dict]:
    """Insert one row silently; return a list of error entries (empty on success)."""
    # Date sanity before hitting the create service (clearer messages/line refs).
    date_fields = {
        "public_holidays": ["start_date"],
        "vacations": ["start_date", "end_date"],
        "exam_windows": ["start_date", "end_date"],
        "events": ["event_date"],
    }[import_type]
    date_errs = [
        {"row": line, "field": f, "message": f"Invalid date in '{f}' (use YYYY-MM-DD)."}
        for f in date_fields
        if not _valid_date(_clean(row, f))
    ]
    if date_errs:
        return date_errs

    try:
        if import_type in ("public_holidays", "vacations"):
            payload = {
                "name": _clean(row, "name"),
                "holiday_type": "vacation" if import_type == "vacations"
                else (_clean(row, "holiday_type") or "public"),
                "start_date": _clean(row, "start_date"),
                "end_date": _clean(row, "end_date") or None,
                "applies_to": _clean(row, "applies_to") or "entire_school",
                "description": _clean(row, "description") or None,
                "academic_year_id": year_id,
            }
            result = holiday_services.create_holiday(payload, g.tenant_id, silent=True)
            return [] if result.get("success") else _row_errors_from_result(result, line)

        if import_type == "exam_windows":
            services.create_exam_window(
                year_id,
                {
                    "name": _clean(row, "name"),
                    "exam_type": _clean(row, "exam_type") or "other",
                    "start_date": _clean(row, "start_date"),
                    "end_date": _clean(row, "end_date"),
                    "description": _clean(row, "description") or None,
                },
                silent=True,
            )
            return []

        # events
        services.create_school_event(
            year_id,
            {
                "name": _clean(row, "name"),
                "event_type": _clean(row, "event_type") or "event",
                "event_date": _clean(row, "event_date"),
                "applies_to": _clean(row, "applies_to") or "entire_school",
                "description": _clean(row, "description") or None,
            },
            silent=True,
        )
        return []
    except services.CalendarValidationError as e:
        return [{"row": line, "field": f, "message": m} for f, m in e.errors.items()]
