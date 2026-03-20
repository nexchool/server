"""
Schedule Module

Today's schedule and related endpoints. Uses timetable data.
Includes per-day override support (substitute teacher, activity, cancelled).
"""

from flask import Blueprint

schedule_bp = Blueprint("schedule", __name__)

from . import routes  # noqa: E402, F401
