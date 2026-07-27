"""Backfill dedupe helper for migration 077.

These tests cover only the pure `distinct_names()` helper — no SQL, no
database fixture. The migration's actual SQL (the ON CONFLICT insert and the
lower(trim())-matching UPDATE) is exercised by really running
`flask db upgrade`/`downgrade` against seeded/real data; see the task report
for that round-trip evidence, not this file.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from migrations import department_backfill  # noqa: E402


def test_distinct_names_dedupe_case_insensitively():
    rows = [("t1", "Maths"), ("t1", "maths"), ("t1", "  MATHS  ")]

    assert department_backfill.distinct_names(rows) == {("t1", "maths"): "Maths"}


def test_distinct_names_keeps_first_seen_casing():
    rows = [("t1", "Higher Secondary"), ("t1", "HIGHER SECONDARY")]

    assert department_backfill.distinct_names(rows) == {
        ("t1", "higher secondary"): "Higher Secondary"
    }


def test_distinct_names_skips_blank_and_null():
    rows = [("t1", None), ("t1", "   "), ("t1", ""), ("t1", "Science")]

    assert department_backfill.distinct_names(rows) == {("t1", "science"): "Science"}


def test_distinct_names_separates_tenants():
    rows = [("t1", "Science"), ("t2", "Science")]

    assert department_backfill.distinct_names(rows) == {
        ("t1", "science"): "Science",
        ("t2", "science"): "Science",
    }
