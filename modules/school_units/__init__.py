"""
School Units Module

Sub-schools / campuses inside a tenant (e.g. "Modi Primary",
"Modi Higher Secondary"). One tenant can have many SchoolUnits.

Phase 2: CRUD API exposed at /api/school-units.
"""

from flask import Blueprint

school_units_bp = Blueprint("school_units", __name__)

from . import models  # noqa: E402, F401
from . import routes  # noqa: E402, F401
