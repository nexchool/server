"""
School Setup Module

Read-only aggregator endpoints used by the UI's school-setup wizard to
load all configuration in one round-trip. No domain logic of its own —
it just composes responses from existing services.

Mounted at /api/school-setup.
"""

from flask import Blueprint

school_setup_bp = Blueprint("school_setup", __name__)

from . import routes  # noqa: E402, F401
from . import models  # noqa: F401  # registers SetupModuleEvent, DataPurgeLog
from . import template_models  # noqa: F401  # registers SubjectTemplateGroup, SubjectTemplateItem
