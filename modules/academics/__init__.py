"""
Academics Module

Academic year management and timeline. Finance consumes via FK only.
"""

from flask import Blueprint

# Application registers this at /api/academics — do not add another /academics prefix here.
academics_bp = Blueprint("academics", __name__)

from .academic_year import routes  # noqa: E402, F401
from . import overview  # noqa: E402, F401
from . import bell_routes  # noqa: E402, F401
from . import dash_routes  # noqa: E402, F401
