from flask import Blueprint

classes_bp = Blueprint('classes', __name__)

from . import routes
from . import subject_load_routes
