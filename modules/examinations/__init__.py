from flask import Blueprint

# REST is deliberately narrow here. Business operations live on GraphQL (the
# examination scheduling and marks-entry fields); this blueprint exists only
# for the two things GraphQL cannot carry — a spreadsheet going up and a
# template coming down — which is the split `graphql-conventions.md` sets and
# the student importer already follows.
examinations_bp = Blueprint("examinations", __name__)

from . import marks_import_routes  # noqa: E402,F401
