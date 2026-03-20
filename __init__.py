"""
School ERP Backend

Production-grade modular backend architecture for School ERP system.

Architecture Overview:
- config/: Configuration management
- core/: Core infrastructure (database, decorators, extensions)
- modules/: Business modules (auth, rbac, users, etc.)
- shared/: Shared utilities and helpers

RBAC Philosophy:
- Authorization via permissions only
- Role names never used in business logic
- Permission naming: resource.action.scope
"""

__version__ = '1.0.0'
