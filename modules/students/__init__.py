from flask import Blueprint

students_bp = Blueprint("students", __name__)

# Static paths (bulk-import/*) must register before /<student_id> in routes.py
from . import bulk_import_routes  # noqa: F401

from . import routes
