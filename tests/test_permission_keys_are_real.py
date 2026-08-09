"""A permission key that nobody seeded denies everyone, quietly.

`has_permission` never looks a key up. It compares the string against the
set the caller holds, so a typo is not an error — it is a route that returns
403 to every non-platform-admin forever, and nobody finds out until a school
reports that a screen "stopped working".

Worse, the deny is not even consistent: `has_permission` falls back to
`f"{resource}.manage"`, so a typo in the *action* segment
(`student.raed.all`) still passes for anyone holding `student.manage`. The
same mistake produces different answers for different people.

These tests are the lookup the resolver does not do: every key checked in a
route, granted by a seeded role, or offerable through the sub-admin catalog
must exist in the catalogue that creates Permission rows.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SERVER = pathlib.Path(__file__).resolve().parent.parent

# The functions whose first (or every) string argument is a permission key.
_DECISION_CALLS = {
    "require_permission",
    "require_any_permission",
    "require_all_permissions",
    "has_permission",
}


def _seeded_keys() -> set:
    """The names `scripts/seed_rbac.py` turns into Permission rows."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_seed_rbac_for_test", SERVER / "scripts" / "seed_rbac.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {name for name, _description in module.PERMISSIONS}


def _module_level_strings(tree: ast.Module) -> dict:
    """`PERM_MANAGE = "student.manage"` — the form most routes use."""
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(
            node.value.value, str
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found[target.id] = node.value.value
    return found


def _keys_checked_in(path: pathlib.Path) -> set:
    """Every permission key this file asks about, literal or via a constant."""
    tree = ast.parse(path.read_text())
    constants = _module_level_strings(tree)
    keys = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name not in _DECISION_CALLS:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                # has_permission(user_id, "x") — the user id is not a key,
                # but it is never a bare string literal, so this is safe.
                keys.add(arg.value)
            elif isinstance(arg, ast.Name) and arg.id in constants:
                keys.add(constants[arg.id])
    return keys


def _source_files():
    for path in SERVER.glob("modules/**/*.py"):
        if "test" in str(path) or "/venv/" in str(path):
            continue
        yield path


def test_every_permission_checked_in_a_route_is_seeded():
    seeded = _seeded_keys()
    offenders = {}
    for path in _source_files():
        unknown = _keys_checked_in(path) - seeded
        if unknown:
            offenders[str(path.relative_to(SERVER))] = sorted(unknown)

    assert not offenders, (
        "These permission keys are checked but never seeded, so they deny "
        "everyone and no error is raised. Add them to scripts/seed_rbac.py "
        f"or fix the spelling:\n{offenders}"
    )


def test_every_permission_a_seeded_role_grants_is_seeded():
    """A granted name with no Permission row grants nothing, silently.

    `role_seeder.py` does `if not perm: continue`, so the role is created
    looking correct and holding less than it says. Both halves now come from
    `modules/rbac/catalog.py`, which makes this a check that the catalogue is
    internally consistent rather than that two files were kept in step by hand.
    """
    from modules.rbac.role_seeder import DEFAULT_ROLES

    seeded = _seeded_keys()
    offenders = {
        role: sorted(set(spec["permissions"]) - seeded)
        for role, spec in DEFAULT_ROLES.items()
        if set(spec["permissions"]) - seeded
    }
    assert not offenders, (
        f"Roles grant permission names that are never created: {offenders}"
    )


def test_every_permission_the_subadmin_catalog_can_grant_is_seeded():
    """The catalog claims its strings are checked against the seed list.

    That claim was prose, performed by hand. A bad name there is dropped by
    `_sync_role_permissions` without complaint, so a School Admin grants a
    module and the sub-admin silently receives less than was selected.
    """
    from modules.sub_admins.catalog import SUBADMIN_MODULES

    seeded = _seeded_keys()
    offered = set()
    for spec in SUBADMIN_MODULES.values():
        for names in spec.get("perms", {}).values():
            offered.update(names)
        for names in spec.get("toggles", {}).values():
            offered.update(names)

    assert not offered - seeded, (
        "The sub-admin catalog can offer permission keys that are never "
        f"created: {sorted(offered - seeded)}"
    )
