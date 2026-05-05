"""
Class-Subjects Module

Thin blueprint that exposes structured bulk operations on the
ClassSubject (subject offering per class) table without taking a
dependency on the classes module's URL space.

Mounted at /api/class-subjects.
"""

from flask import Blueprint

class_subjects_bp = Blueprint("class_subjects", __name__)

from . import routes  # noqa: E402, F401
