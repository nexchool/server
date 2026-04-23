"""
Tenant-configurable sequential ID patterns for students (admission numbers) and teachers (employee IDs).

Pattern language:
  - {YEAR} — current 4-digit calendar year (e.g. 2026)
  - {YY}   — last two digits of the year (e.g. 26)
  - {SEQ:n} — exactly one sequence segment at the end, zero-padded to n digits (n = 1..9)

Defaults: students "ADM{YEAR}{SEQ:3}", teachers "TCH{YEAR}{SEQ:3}".
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional, Set, Type

SEQ_SUFFIX_RE = re.compile(r"^(?P<before>.*)\{SEQ:([1-9])\}$")

DEFAULT_STUDENT_ADMISSION_PATTERN = "ADM{YEAR}{SEQ:3}"
DEFAULT_TEACHER_EMPLOYEE_PATTERN = "TCH{YEAR}{SEQ:3}"

MAX_STUDENT_ID_LEN = 20
MAX_TEACHER_ID_LEN = 20


def _now_year() -> int:
    return datetime.utcnow().year


def substitute_year_tokens(fragment: str, year: int) -> str:
    s = fragment.replace("{YEAR}", str(year))
    return s.replace("{YY}", str(year)[-2:])


def parse_seq_width(pattern: str) -> int:
    m = SEQ_SUFFIX_RE.match(pattern.strip())
    if not m:
        raise ValueError("Pattern must end with {SEQ:n} where n is 1-9")
    return int(m.group(2))


def render_id(pattern: str, year: int, seq: int) -> str:
    m = SEQ_SUFFIX_RE.match(pattern.strip())
    if not m:
        raise ValueError("Pattern must end with {SEQ:n}")
    before, width_s = m.group(1), m.group(2)
    width = int(width_s)
    if seq < 0 or seq >= 10**width:
        raise ValueError("Sequence out of range for pattern width")
    body = substitute_year_tokens(before, year)
    return body + f"{seq:0{width}d}"


def build_scan_prefix(pattern: str, year: int) -> str:
    m = SEQ_SUFFIX_RE.match(pattern.strip())
    if not m:
        return ""
    before = m.group(1)
    return substitute_year_tokens(before, year)


def validate_id_pattern(
    pattern: str,
    *,
    max_len: int,
    year: Optional[int] = None,
) -> Optional[str]:
    """Return an error string if invalid, else None."""
    if not pattern or not str(pattern).strip():
        return "Pattern cannot be empty"
    p = str(pattern).strip()
    m = SEQ_SUFFIX_RE.match(p)
    if not m:
        return (
            "Pattern must end with a single {SEQ:n} (e.g. {SEQ:3}) with n from 1 to 9, "
            "and nothing after that token."
        )
    before = m.group(1)
    if p.count("{SEQ:") != 1:
        return "Pattern must include exactly one {SEQ:n} at the end."
    tmp = before
    for token in ("{YEAR}", "{YY}"):
        tmp = tmp.replace(token, "")
    if "{" in tmp or "}" in tmp:
        return "Only {YEAR}, {YY}, and a single trailing {SEQ:n} are allowed."
    if "{YEAR}" not in before and "{YY}" not in before:
        return "Include {YEAR} or {YY} in the pattern so new numbers are grouped by year."
    y = year if year is not None else _now_year()
    try:
        sample = render_id(p, y, 1)
        width = int(m.group(2))
        high = render_id(p, y, 10**width - 1)
    except ValueError as e:
        return str(e) or "Invalid pattern"
    for cand in (sample, high):
        if len(cand) > max_len:
            return f"Generated id would be too long (max {max_len} characters)."
    return None


def max_seq_for_tenant(
    tenant_id: str,
    model: Type[Any],
    col_name: str,
    pattern: str,
    year: Optional[int] = None,
) -> int:
    y = year if year is not None else _now_year()
    col = getattr(model, col_name)
    width = parse_seq_width(pattern)
    prefix = build_scan_prefix(pattern, y)
    if not prefix:
        return 0
    rows = (
        model.query.filter(
            model.tenant_id == tenant_id,
            col.like(f"{prefix}%"),
        )
        .order_by(col.desc())
        .limit(200)
        .all()
    )
    best = 0
    for row in rows:
        val = getattr(row, col_name)
        if not isinstance(val, str) or not val.startswith(prefix):
            continue
        tail = val[len(prefix) :]
        if not tail.isdigit() or len(tail) != width:
            continue
        best = max(best, int(tail))
    return best


def allocate_next_id(
    *,
    tenant_id: str,
    model: Type[Any],
    col_name: str,
    pattern: str,
    reserved: Optional[Set[str]] = None,
    year: Optional[int] = None,
    max_len: int = 20,
) -> str:
    y = year if year is not None else _now_year()
    start = max_seq_for_tenant(tenant_id, model, col_name, pattern, y) + 1
    seq = start
    reserved = reserved or set()
    for _ in range(10000):
        cand = render_id(pattern, y, seq)
        if len(cand) > max_len:
            raise RuntimeError("Generated ID exceeds maximum length")
        if cand in reserved:
            seq += 1
            continue
        exists = model.query.filter_by(tenant_id=tenant_id, **{col_name: cand}).first()
        if not exists:
            return cand
        seq += 1
    raise RuntimeError("Could not allocate a unique id")


def get_student_admission_pattern(tenant_id: str) -> str:
    from modules.academics.backbone.models import AcademicSettings

    row = AcademicSettings.query.filter_by(tenant_id=tenant_id).first()
    raw = (getattr(row, "admission_number_format", None) or "").strip() if row else ""
    return raw or DEFAULT_STUDENT_ADMISSION_PATTERN


def get_teacher_employee_pattern(tenant_id: str) -> str:
    from modules.academics.backbone.models import AcademicSettings

    row = AcademicSettings.query.filter_by(tenant_id=tenant_id).first()
    raw = (getattr(row, "teacher_employee_id_format", None) or "").strip() if row else ""
    return raw or DEFAULT_TEACHER_EMPLOYEE_PATTERN
