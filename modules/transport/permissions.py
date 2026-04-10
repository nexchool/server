"""Transport module permission constants (granular + legacy transport.manage)."""

# Legacy — full transport access (seeded for admin)
TRANSPORT_MANAGE = "transport.manage"

# Buses
TRANSPORT_BUSES_CREATE = "transport.buses.create"
TRANSPORT_BUSES_READ = "transport.buses.read"
TRANSPORT_BUSES_UPDATE = "transport.buses.update"
TRANSPORT_BUSES_DELETE = "transport.buses.delete"

# Drivers (legacy table)
TRANSPORT_DRIVERS_CREATE = "transport.drivers.create"
TRANSPORT_DRIVERS_READ = "transport.drivers.read"
TRANSPORT_DRIVERS_UPDATE = "transport.drivers.update"
TRANSPORT_DRIVERS_DELETE = "transport.drivers.delete"

# Routes
TRANSPORT_ROUTES_CREATE = "transport.routes.create"
TRANSPORT_ROUTES_READ = "transport.routes.read"
TRANSPORT_ROUTES_UPDATE = "transport.routes.update"
TRANSPORT_ROUTES_DELETE = "transport.routes.delete"

# Stops
TRANSPORT_STOPS_CREATE = "transport.stops.create"
TRANSPORT_STOPS_READ = "transport.stops.read"
TRANSPORT_STOPS_UPDATE = "transport.stops.update"
TRANSPORT_STOPS_DELETE = "transport.stops.delete"

# Assignments
TRANSPORT_ASSIGNMENTS_CREATE = "transport.assignments.create"
TRANSPORT_ASSIGNMENTS_READ = "transport.assignments.read"
TRANSPORT_ASSIGNMENTS_UPDATE = "transport.assignments.update"
TRANSPORT_ASSIGNMENTS_DELETE = "transport.assignments.delete"

# Enrollments
TRANSPORT_ENROLLMENT_CREATE = "transport.enrollment.create"
TRANSPORT_ENROLLMENT_READ = "transport.enrollment.read"
TRANSPORT_ENROLLMENT_UPDATE = "transport.enrollment.update"
TRANSPORT_ENROLLMENT_DELETE = "transport.enrollment.delete"

# Fee plans
TRANSPORT_FEE_PLANS_READ = "transport.fee_plans.read"
TRANSPORT_FEE_PLANS_MANAGE = "transport.fee_plans.manage"

# Dashboard / exports
TRANSPORT_DASHBOARD_READ = "transport.dashboard.read"
TRANSPORT_EXPORTS_READ = "transport.exports.read"

# Student/parent read own (mobile)
TRANSPORT_STUDENT_READ_OWN = "transport.student.read_own"

ALL_TRANSPORT_PERMISSIONS = [
    TRANSPORT_MANAGE,
    TRANSPORT_BUSES_CREATE,
    TRANSPORT_BUSES_READ,
    TRANSPORT_BUSES_UPDATE,
    TRANSPORT_BUSES_DELETE,
    TRANSPORT_DRIVERS_CREATE,
    TRANSPORT_DRIVERS_READ,
    TRANSPORT_DRIVERS_UPDATE,
    TRANSPORT_DRIVERS_DELETE,
    TRANSPORT_ROUTES_CREATE,
    TRANSPORT_ROUTES_READ,
    TRANSPORT_ROUTES_UPDATE,
    TRANSPORT_ROUTES_DELETE,
    TRANSPORT_STOPS_CREATE,
    TRANSPORT_STOPS_READ,
    TRANSPORT_STOPS_UPDATE,
    TRANSPORT_STOPS_DELETE,
    TRANSPORT_ASSIGNMENTS_CREATE,
    TRANSPORT_ASSIGNMENTS_READ,
    TRANSPORT_ASSIGNMENTS_UPDATE,
    TRANSPORT_ASSIGNMENTS_DELETE,
    TRANSPORT_ENROLLMENT_CREATE,
    TRANSPORT_ENROLLMENT_READ,
    TRANSPORT_ENROLLMENT_UPDATE,
    TRANSPORT_ENROLLMENT_DELETE,
    TRANSPORT_FEE_PLANS_READ,
    TRANSPORT_FEE_PLANS_MANAGE,
    TRANSPORT_DASHBOARD_READ,
    TRANSPORT_EXPORTS_READ,
    TRANSPORT_STUDENT_READ_OWN,
]
