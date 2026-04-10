from flask import Blueprint

transport_bp = Blueprint("transport", __name__)

from . import routes  # noqa: E402, F401
