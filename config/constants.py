"""
Application Constants

Centralized location for all application-wide constants.
"""

# Permission naming convention
PERMISSION_NAMING_CONVENTION = "resource.action.scope"

# Common permission actions
PERMISSION_ACTIONS = {
    'CREATE': 'create',
    'READ': 'read',
    'UPDATE': 'update',
    'DELETE': 'delete',
    'MANAGE': 'manage',  # Implies all actions on resource
}

# Permission scopes
PERMISSION_SCOPES = {
    'SELF': 'self',      # Only own resources
    'CLASS': 'class',    # Within assigned class
    'SCHOOL': 'school',  # School-wide access
    'ALL': 'all',        # System-wide (super admin)
}

# HTTP Status Codes (for consistency)
HTTP_200_OK = 200
HTTP_201_CREATED = 201
HTTP_400_BAD_REQUEST = 400
HTTP_401_UNAUTHORIZED = 401
HTTP_403_FORBIDDEN = 403
HTTP_404_NOT_FOUND = 404
HTTP_409_CONFLICT = 409
HTTP_500_INTERNAL_SERVER_ERROR = 500

# Standard error messages
ERROR_MESSAGES = {
    'AUTH_REQUIRED': 'Authentication required',
    'INVALID_TOKEN': 'Invalid or expired token',
    'INSUFFICIENT_PERMISSIONS': 'Insufficient permissions',
    'USER_NOT_FOUND': 'User not found',
    'INVALID_CREDENTIALS': 'Invalid credentials',
    'EMAIL_ALREADY_EXISTS': 'Email already exists',
    'VALIDATION_ERROR': 'Validation error',
}

# Success messages
SUCCESS_MESSAGES = {
    'CREATED': 'Resource created successfully',
    'UPDATED': 'Resource updated successfully',
    'DELETED': 'Resource deleted successfully',
}

# Pagination defaults
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Date/Time formats
DATE_FORMAT = '%Y-%m-%d'
DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
TIME_FORMAT = '%H:%M:%S'
