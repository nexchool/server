"""People does not know that accounts exist.

People is the domain everything else depends on, so it must depend on nothing.
A person signs in, works here, studies here — but People learns those by
reading the relationships each module declares onto Person, never by importing
the module that owns them (ADR-001, ADR-012).

Checked at the import level rather than through behaviour, because a boundary
that is only tested by what the code happens to do today is not a boundary.
"""

from __future__ import annotations

import ast
import pathlib

# Migration-era only: it walks accounts to give the people they imply, which is
# the whole job. It takes the rule for doing so *from* Identity rather than
# holding its own copy. Goes when the backfill goes.
MIGRATION_ERA = {"backfill.py"}

PEOPLE = pathlib.Path(__file__).resolve().parents[1] / "modules" / "people"


def _imported_modules(source: str):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name


def test_people_imports_nothing_from_identity():
    offenders = []

    for path in sorted(PEOPLE.glob("*.py")):
        if path.name in MIGRATION_ERA:
            continue
        for module in _imported_modules(path.read_text()):
            if module.startswith("modules.auth"):
                offenders.append(f"{path.name} imports {module}")

    assert not offenders, (
        "People must not know Identity exists. Ask the person what "
        "relationships they hold instead:\n  " + "\n  ".join(offenders)
    )


def test_people_imports_nothing_from_academic():
    """The same rule for the modules People is depended on by."""
    forbidden = ("modules.students", "modules.teachers", "modules.classes",
                 "modules.academics")
    offenders = []

    for path in sorted(PEOPLE.glob("*.py")):
        if path.name in MIGRATION_ERA:
            continue
        for module in _imported_modules(path.read_text()):
            if module.startswith(forbidden):
                offenders.append(f"{path.name} imports {module}")

    assert not offenders, (
        "People must not reach into Academic:\n  " + "\n  ".join(offenders)
    )
