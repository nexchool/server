"""Tests for RBAC seed — audit_log.view permission definition and admin assignment.

Pure-Python — reads the PERMISSIONS list and ROLES dict from scripts/seed_rbac.py
by extracting them via AST (avoiding the Flask app bootstrap that the module triggers
at import time).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
SEED_FILE = SERVER_DIR / "scripts" / "seed_rbac.py"


def _extract_seed_data():
    """Parse seed_rbac.py and return (permissions_list, roles_dict) without importing it."""
    source = SEED_FILE.read_text()
    tree = ast.parse(source)

    permissions = []
    roles = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id == "PERMISSIONS":
                        # List of tuples: [('name', 'desc'), ...]
                        if isinstance(node.value, ast.List):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Tuple) and len(elt.elts) >= 1:
                                    name_node = elt.elts[0]
                                    if isinstance(name_node, ast.Constant):
                                        permissions.append(name_node.value)

                    if target.id == "ROLES":
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


def test_audit_log_view_in_permissions():
    """audit_log.view must be present in the PERMISSIONS list."""
    permissions, _ = _extract_seed_data()
    assert "audit_log.view" in permissions, (
        "audit_log.view not found in PERMISSIONS — add it to scripts/seed_rbac.py"
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
        "add it to the Admin role's permissions list in scripts/seed_rbac.py"
    )
    assert "Admin" in admin_roles_with_perm, (
        f"audit_log.view was found in {admin_roles_with_perm} but not in 'Admin'"
    )
