"""Subject contexts: per-(programme, grade) offerings of a subject.

The single source of truth for what subjects a grade offers and how.
Mounted at /api/subject-contexts.
"""

from flask import Blueprint

subject_contexts_bp = Blueprint("subject_contexts", __name__)

from . import models  # noqa: E402, F401
from . import routes  # noqa: E402, F401
