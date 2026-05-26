"""
Religions Module

Tenant-scoped master list of religions used in student / teacher
demographics. Each tenant curates the values that match its admission
forms and reporting needs.

Phase 2: CRUD API exposed at /api/religions.
"""

from flask import Blueprint

religions_bp = Blueprint("religions", __name__)

from . import models  # noqa: E402, F401
from . import routes  # noqa: E402, F401
