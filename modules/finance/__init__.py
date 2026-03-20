"""
Finance (Fees Collection) Module

Fee structures, student fees, payments, audit logging.
"""

from flask import Blueprint

finance_bp = Blueprint("finance", __name__, url_prefix="/finance")

from . import routes  # noqa: E402, F401
