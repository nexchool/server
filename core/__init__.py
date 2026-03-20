"""
Core Infrastructure Module

This module contains the foundational components of the application:
- Database instance
- Flask extensions
- Decorators for authentication and authorization
"""

from .database import db
from .extensions import cors, mail

__all__ = ['db', 'cors', 'mail']
