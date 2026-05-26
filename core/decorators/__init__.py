"""
Decorators Module

This module provides decorators for authentication, authorization, and multi-tenant.

RBAC Philosophy:
- Authorization via permissions only
- Role names never used in business logic
- Permission naming: resource.action.scope

Usage:
    from core.decorators import auth_required, require_permission, tenant_required

    @bp.route('/protected')
    @auth_required
    def protected_route():
        return jsonify({'message': 'Success'})

    @bp.route('/admin')
    @auth_required
    @require_permission('user.manage')
    def admin_route():
        return jsonify({'message': 'Admin access'})

    @bp.route('/students')
    @tenant_required
    @auth_required
    def list_students():
        ...
"""

from .auth import auth_required
from .rbac import require_permission, require_any_permission, require_all_permissions
from .platform import platform_admin_required
from .setup import require_setup_complete
from .subscription import require_active_subscription, get_subscription_state
from core.tenant import tenant_required
from core.feature_flags import require_feature
# Back-compat alias; new code should import require_feature directly.
require_plan_feature = require_feature

__all__ = [
    'auth_required',
    'require_permission',
    'require_any_permission',
    'require_all_permissions',
    'tenant_required',
    'platform_admin_required',
    'require_feature',
    'require_plan_feature',
    'require_setup_complete',
    'require_active_subscription',
    'get_subscription_state',
]
