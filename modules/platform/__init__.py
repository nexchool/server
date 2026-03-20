"""Platform (Super Admin) module."""

from flask import Blueprint

platform_bp = Blueprint("platform", __name__, url_prefix="/platform")

from backend.modules.platform import routes  # noqa: E402, F401
