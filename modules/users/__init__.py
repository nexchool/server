"""
Users Management Module

Handles user administration, CRUD operations, and user management features.
Separate from auth module which handles authentication/sessions.

Components:
- routes: User management endpoints
- services: User business logic
"""

from flask import Blueprint

# Create the users blueprint
users_bp = Blueprint('users', __name__)

# Import routes to register them with the blueprint
from . import routes

__all__ = ['users_bp']
