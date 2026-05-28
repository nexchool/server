"""Global search module."""

from flask import Blueprint

search_bp = Blueprint("search", __name__)

from modules.search import routes  # noqa: E402,F401
