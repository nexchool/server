"""Student leave permission constants.

These strings ARE the permission identifiers checked at runtime via
@require_permission(...) on routes and has_permission(user, perm) at the service
layer. Keep this in sync with:
  - server/modules/rbac/role_seeder.py (DEFAULT_ROLES dict)
  - server/scripts/seed_rbac.py (PERMISSIONS catalog + per-role lists)
"""

PERM_STUDENT_LEAVE_APPLY = "student.leave.apply"
PERM_STUDENT_LEAVE_READ_OWN = "student.leave.read.own"
PERM_STUDENT_LEAVE_READ_CLASS = "student.leave.read.class"
PERM_STUDENT_LEAVE_READ_ALL = "student.leave.read.all"
PERM_STUDENT_LEAVE_APPROVE_CLASS = "student.leave.approve.class"
PERM_STUDENT_LEAVE_APPROVE_ALL = "student.leave.approve.all"
PERM_STUDENT_LEAVE_REQUEST_CANCEL = "student.leave.request_cancel"


ALL_STUDENT_LEAVE_PERMISSIONS = (
    PERM_STUDENT_LEAVE_APPLY,
    PERM_STUDENT_LEAVE_READ_OWN,
    PERM_STUDENT_LEAVE_READ_CLASS,
    PERM_STUDENT_LEAVE_READ_ALL,
    PERM_STUDENT_LEAVE_APPROVE_CLASS,
    PERM_STUDENT_LEAVE_APPROVE_ALL,
    PERM_STUDENT_LEAVE_REQUEST_CANCEL,
)
