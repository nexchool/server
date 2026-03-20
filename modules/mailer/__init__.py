"""
Mailer Module

Email service for sending templated emails.
Uses SMTP with Jinja2 templates.
"""

from .service import send_email, send_template_email

__all__ = ['send_email', 'send_template_email']
