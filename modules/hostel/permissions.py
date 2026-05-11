"""Hostel module RBAC permission constants.

All routes use these constants (never raw strings) so renames stay
mechanical. Permission seeds live in scripts/seed_rbac.py.
"""

# Hostels / rooms / beds (facility administration)
HOSTEL_READ = "hostel.read"               # list / view hostels, rooms, beds
HOSTEL_MANAGE = "hostel.manage"           # create / edit / delete hostels, rooms, beds

# Allocations
HOSTEL_ALLOC_READ = "hostel.allocations.read"
HOSTEL_ALLOC_MANAGE = "hostel.allocations.manage"

# Visitors
HOSTEL_VISITOR_READ = "hostel.visitors.read"
HOSTEL_VISITOR_MANAGE = "hostel.visitors.manage"

# Gatepasses
HOSTEL_GP_CREATE = "hostel.gatepass.create"      # student or warden creates request
HOSTEL_GP_APPROVE = "hostel.gatepass.approve"    # warden approves / rejects
HOSTEL_GP_GATEKEEPER = "hostel.gatepass.gatekeeper"  # checkout / checkin at gate
HOSTEL_GP_READ = "hostel.gatepass.read"

# Reports / dashboard
HOSTEL_REPORTS_READ = "hostel.reports.read"

ALL_HOSTEL_PERMISSIONS = (
    (HOSTEL_READ, "View hostels, rooms, and beds"),
    (HOSTEL_MANAGE, "Create / update / delete hostels, rooms, and beds"),
    (HOSTEL_ALLOC_READ, "View allocations"),
    (HOSTEL_ALLOC_MANAGE, "Allocate students to beds / check out"),
    (HOSTEL_VISITOR_READ, "View visitor logs"),
    (HOSTEL_VISITOR_MANAGE, "Check visitors in / out"),
    (HOSTEL_GP_CREATE, "Create gatepass requests"),
    (HOSTEL_GP_APPROVE, "Approve or reject gatepasses (warden)"),
    (HOSTEL_GP_GATEKEEPER, "Mark gatepass checkout / checkin at the gate"),
    (HOSTEL_GP_READ, "View gatepasses"),
    (HOSTEL_REPORTS_READ, "View occupancy reports and dashboard"),
)
