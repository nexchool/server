"""
RBAC (Role-Based Access Control) Module

Handles roles, permissions, and access control.

RBAC Philosophy:
- Authorization via permissions only
- Role names never used in business logic
- Permission naming: resource.action.scope
- 'manage' permission implies all actions on that resource

Components:
- models: Role, Permission, RolePermission, UserRole models
- routes: RBAC management endpoints (admin only)
- services: RBAC business logic
"""

from flask import Blueprint

# Create the RBAC blueprint
rbac_bp = Blueprint('rbac', __name__)

# Import routes to register them with the blueprint
from . import routes

__all__ = ['rbac_bp']
