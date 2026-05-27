"""Announcement permission constants.

Keep in sync with:
  - server/modules/rbac/role_seeder.py (DEFAULT_ROLES dict)
  - server/scripts/seed_rbac.py (PERMISSIONS catalog + per-role lists)
"""

PERM_ANNOUNCEMENT_CREATE = "announcement.create"
PERM_ANNOUNCEMENT_UPDATE = "announcement.update"
PERM_ANNOUNCEMENT_RECALL = "announcement.recall"
PERM_ANNOUNCEMENT_READ_OWN = "announcement.read.own"
PERM_ANNOUNCEMENT_READ_ALL = "announcement.read.all"


ALL_ANNOUNCEMENT_PERMISSIONS = (
    PERM_ANNOUNCEMENT_CREATE,
    PERM_ANNOUNCEMENT_UPDATE,
    PERM_ANNOUNCEMENT_RECALL,
    PERM_ANNOUNCEMENT_READ_OWN,
    PERM_ANNOUNCEMENT_READ_ALL,
)
