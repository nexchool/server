"""Mediums of instruction (English, Gujarati, ...). Mounted at /api/mediums."""

from flask import Blueprint

mediums_bp = Blueprint("mediums", __name__)

from . import models  # noqa: E402, F401
from . import routes  # noqa: E402, F401
