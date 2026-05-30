"""GET /api/search — aggregating global search."""

from __future__ import annotations

from flask import g, request

from core.decorators import auth_required, tenant_required
from core.feature_flags import require_feature
from shared.helpers import success_response
from modules.search import search_bp
from modules.search.services import global_search


@search_bp.route("", methods=["GET"])
@tenant_required
@auth_required
@require_feature("search")
def search():
    q = request.args.get("q", "")
    try:
        limit = int(request.args.get("limit", 5))
    except (TypeError, ValueError):
        limit = 5
    results = global_search(g.current_user, q, limit=limit)
    return success_response(data=results)
