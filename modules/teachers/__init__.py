from flask import Blueprint

teachers_bp = Blueprint('teachers', __name__)

from . import routes
from . import constraint_routes
