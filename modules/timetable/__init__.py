"""
Timetable Module

The signed-in person's own weekly timetable, read from the class timetables
(`TimetableVersion` + `TimetableEntry`) that `/api/classes/<id>/timetable`
owns. This module holds no timetable data of its own.
"""

from flask import Blueprint

timetable_bp = Blueprint("timetable", __name__)

from . import routes  # noqa: E402, F401
