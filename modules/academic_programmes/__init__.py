"""
Academic Programmes Module

Board + optional medium of instruction (e.g. "CBSE", "GSEB Gujarati").
Classes reference exactly one programme so the same grade name can exist in
parallel across programmes inside a tenant.

Phase 2: CRUD API exposed at /api/programmes.
"""

from flask import Blueprint

academic_programmes_bp = Blueprint("academic_programmes", __name__)

from . import models  # noqa: E402, F401
from . import routes  # noqa: E402, F401
