"""Tests for RBAC seed — audit_log.view permission definition and admin assignment.

Pure-Python — reads the catalogue by AST rather than importing it, because
`scripts/seed_rbac.py` bootstraps the Flask app at import time and this needs
neither an app nor a database.

The literals moved: they used to be written out in `scripts/seed_rbac.py`, and
both seeders now import them from `modules/rbac/catalog.py`. Parsing the script
after that finds two imports and no data, which is how this test started passing
vacuously enough to fail loudly. Read the catalogue instead.
"""
from __future__ import annotations

import ast
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
SEED_FILE = SERVER_DIR / "modules" / "rbac" / "catalog.py"


def _extract_seed_data():
    """Parse catalog.py and return (permissions_list, roles_dict) without importing it."""
    source = SEED_FILE.read_text()
    tree = ast.parse(source)

    permissions = []
    roles = {}

    # Both forms: `PERMISSIONS = [...]` and the catalogue's annotated
    # `PERMISSIONS: List[Tuple[str, str]] = [...]`, which is an AnnAssign and
    # which an Assign-only walk reads straight past into an empty list.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    if target.id == "PERMISSIONS":
                        # List of tuples: [('name', 'desc'), ...]
                        if isinstance(node.value, ast.List):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Tuple) and len(elt.elts) >= 1:
                                    name_node = elt.elts[0]
                                    if isinstance(name_node, ast.Constant):
                                        permissions.append(name_node.value)

                    if target.id == "DEFAULT_ROLES":
                        # Dict: {'RoleName': {'permissions': ['perm1', ...]}}
                        if isinstance(node.value, ast.Dict):
                            for key_node, val_node in zip(node.value.keys, node.value.values):
                                if not isinstance(key_node, ast.Constant):
                                    continue
                                role_name = key_node.value
                                perms = []
                                if isinstance(val_node, ast.Dict):
                                    for rk, rv in zip(val_node.keys, val_node.values):
                                        if (
                                            isinstance(rk, ast.Constant)
                                            and rk.value == "permissions"
                                            and isinstance(rv, ast.List)
                                        ):
                                            for p in rv.elts:
                                                if isinstance(p, ast.Constant):
                                                    perms.append(p.value)
                                roles[role_name] = perms

    return permissions, roles


def test_the_catalogue_is_actually_being_read():
    """Guards the two tests below against passing on an empty parse.

    They read the catalogue by AST, and an extractor that stops matching — as it
    did when the literals moved and became annotated assignments — yields empty
    lists. Empty lists make a `not in` assertion fail loudly here, but would make
    any `all(...)` style assertion pass silently.
    """
    permissions, roles = _extract_seed_data()
    assert len(permissions) > 100, f"only parsed {len(permissions)} permissions"
    assert set(roles) == {"Admin", "Teacher", "Student", "Parent"}


def test_audit_log_view_in_permissions():
    """audit_log.view must be present in the PERMISSIONS list."""
    permissions, _ = _extract_seed_data()
    assert "audit_log.view" in permissions, (
        "audit_log.view not found in PERMISSIONS — add it to modules/rbac/catalog.py"
    )


def test_audit_log_view_granted_to_admin_role():
    """audit_log.view must be assigned to the Admin role bundle."""
    _, roles = _extract_seed_data()

    admin_roles_with_perm = [
        role_name
        for role_name, perms in roles.items()
        if "audit_log.view" in perms
    ]
    assert admin_roles_with_perm, (
        "audit_log.view is not assigned to any role in ROLES — "
        "add it to the Admin role's permissions list in modules/rbac/catalog.py"
    )
    assert "Admin" in admin_roles_with_perm, (
        f"audit_log.view was found in {admin_roles_with_perm} but not in 'Admin'"
    )
