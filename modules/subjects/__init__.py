"""
Subjects Module

Subject management for School ERP. Subjects are tenant-scoped.
"""

from flask import Blueprint

subjects_bp = Blueprint("subjects", __name__)

from . import routes  # noqa: E402, F401
