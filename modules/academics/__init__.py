"""
Academics Module

Academic year management and timeline. Finance consumes via FK only.
"""

from flask import Blueprint

academics_bp = Blueprint("academics", __name__, url_prefix="/academics")

from .academic_year import routes  # noqa: E402, F401
from . import overview  # noqa: E402, F401
