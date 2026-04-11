from flask import Blueprint

teachers_bp = Blueprint("teachers", __name__)

# Static paths (bulk-import/*) must register before /<teacher_id> in routes.py
from . import bulk_import_routes  # noqa: F401

from . import routes
from . import constraint_routes
