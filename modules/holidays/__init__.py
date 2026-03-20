from flask import Blueprint

holidays_bp = Blueprint('holidays', __name__)

from . import routes
