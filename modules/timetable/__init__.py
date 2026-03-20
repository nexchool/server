"""
Timetable Module

Manages class timetables: slots per class, day, period with subject and teacher.
"""

from flask import Blueprint

timetable_bp = Blueprint("timetable", __name__)

from . import routes  # noqa: E402, F401
