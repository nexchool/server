"""
Sub-Admins Module

Tenant-scoped management of additional admin accounts ("sub-admins") with a
limited, explicitly-chosen set of module permissions. Gated by the
``subadmin.manage`` permission (seeded onto the tenant "Admin" role only).

Components:
- catalog: SUBADMIN_MODULES single source of truth + expand/summarize helpers
- services: business logic
- routes: thin HTTP layer
"""

from flask import Blueprint

sub_admins_bp = Blueprint("sub_admins", __name__)

from . import routes  # noqa: E402,F401

__all__ = ["sub_admins_bp"]
