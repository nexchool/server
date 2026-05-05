"""
Grades Module

Master list of standards / grades a tenant offers (LKG, UKG, 1..12).
Classes reference a Grade rather than carrying free-text grade names so
the same grade can be reused across programmes.

Phase 2: CRUD API exposed at /api/grades.
"""

from flask import Blueprint

grades_bp = Blueprint("grades", __name__)

from . import models  # noqa: E402, F401
from . import routes  # noqa: E402, F401
