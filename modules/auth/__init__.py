"""
Authentication Module

Handles user authentication, session management, and JWT tokens.

Components:
- models: User and Session models
- routes: Authentication endpoints (login, register, logout, etc.)
- services: Authentication business logic
"""

from flask import Blueprint

# Create the auth blueprint
auth_bp = Blueprint('auth', __name__)

# Import routes to register them with the blueprint
from . import routes

__all__ = ['auth_bp']
