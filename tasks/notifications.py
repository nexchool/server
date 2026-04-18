"""Notification tasks - async email sending."""

import logging
import os

from celery_app import get_celery
from core.extensions import mail

# Worker loads via celery_worker; get_celery returns init'd instance
celery_app = get_celery()
logger = logging.getLogger(__name__)

def _resolve_sender():
    """
    Resolve a sender for Flask-Mail.

    Some environments may not propagate MAIL_* config into the Celery worker
    exactly as the web process does. Setting sender explicitly prevents
    "default sender not configured" failures.
    """
    raw = (os.getenv("MAIL_DEFAULT_SENDER") or "").strip()
    username = (os.getenv("MAIL_USERNAME") or os.getenv("EMAIL_ADDRESS") or "").strip()
    sender_name = (os.getenv("DEFAULT_SENDER_NAME") or "").strip()

    sender_email = raw or username
    if sender_name and sender_email and sender_email == username:
        return (sender_name, sender_email)
    return sender_email or None


@celery_app.task(bind=True, name="send_email_task")
def send_email_task(self, to_email: str, subject: str, body: str, is_html: bool = True):
    """
    Send email asynchronously. Runs with Flask app context (ContextTask).
    """
    try:
        from flask_mail import Message
        sender = _resolve_sender()
        msg = Message(
            subject=subject,
            body=body or "",
            recipients=[to_email],
            sender=sender,
        )
        if is_html:
            msg.html = body or ""
        mail.send(msg)
        return True
    except Exception as e:
        logger.exception("send_email_task failed for %s: %s", to_email, e)
        return False
