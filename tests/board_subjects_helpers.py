"""Shared readers for scripts/board_subjects.json.

Both catalogue test modules walk the same immutable JSON file, and the walk has
one awkward shape: Std 1-10 nodes keep a flat `subjects` list while Std 11-12
nodes fan out per stream. Keeping that shape-switch in one place means a future
change to the catalogue's nesting is a single edit rather than a hunt for copies.

These are stateless pure readers, so sharing them creates no ordering coupling
between tests.
"""
from __future__ import annotations

import json
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
CATALOGUE = SERVER_DIR / "scripts" / "board_subjects.json"


def load_catalogue() -> dict:
    with CATALOGUE.open() as fh:
        return json.load(fh)


def iter_subject_groups(node: dict) -> list[list[dict]]:
    """Std 1-10 nodes keep a flat `subjects` list; Std 11-12 fan out per stream."""
    if "subjects" in node:
        return [node["subjects"]]
    return [s["subjects"] for s in node["streams"].values()]


def iter_subjects(catalogue: dict | None = None):
    """Yield (board_code, standard, subject) for every subject in the catalogue."""
    boards = (catalogue or load_catalogue())["boards"]
    for board_code, board in boards.items():
        for standard, node in board["standards"].items():
            for subjects in iter_subject_groups(node):
                for subject in subjects:
                    yield board_code, int(standard), subject
