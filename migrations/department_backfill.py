"""Pure helper for migration 077's teacher-department backfill.

Kept separate from the revision file so the dedupe rule can be tested directly.
"""

from __future__ import annotations

from typing import Dict, Iterable, Tuple


def distinct_names(rows: Iterable[Tuple[str, str]]) -> Dict[Tuple[str, str], str]:
    """Map (tenant_id, lowercased name) -> first-seen original casing.

    Blank and NULL department values are skipped. Deduping on the lowercased
    form is required: the target unique index is case-insensitive, so emitting
    both "Maths" and "maths" would abort the migration.
    """
    result: Dict[Tuple[str, str], str] = {}
    for tenant_id, raw_name in rows:
        if raw_name is None:
            continue
        name = str(raw_name).strip()
        if not name:
            continue
        key = (tenant_id, name.lower())
        if key not in result:
            result[key] = name
    return result
