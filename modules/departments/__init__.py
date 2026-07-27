"""Departments — per-tenant academic department catalogue."""

from flask import Blueprint

departments_bp = Blueprint("departments", __name__)

# from . import routes  # noqa: E402,F401  — uncommented in Task 4, when routes.py exists
