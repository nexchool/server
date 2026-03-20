"""
Audit module.

Logging for critical features within the school app (e.g. fees management).
Writes to backend.core.models.AuditLog with tenant_id for tenant-scoped audit trail.
Separate from platform/super admin audit used in platform panel.
"""
