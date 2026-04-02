"""
Logical folder segments under S3_ENV_PREFIX for object keys.

Keys are built as: {S3_ENV_PREFIX}/{folder_path}/{unique_filename}
"""

# Top-level segments (use with tenants/students/... as needed)
STUDENTS = "students"
TEACHERS = "teachers"
TEMP = "temp"
EXPORTS = "exports"
TENANTS = "tenants"
PROFILE_PICTURES = "profile-pictures"
DOCUMENTS = "documents"
