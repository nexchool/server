"""Student leave management module."""

from flask import Blueprint

student_leaves_bp = Blueprint("student_leaves", __name__)

from . import routes  # noqa: E402,F401
