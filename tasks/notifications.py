"""Notification tasks - async email sending."""

import logging

from celery_app import get_celery
from core.extensions import mail

# Worker loads via celery_worker; get_celery returns init'd instance
celery_app = get_celery()
logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="send_email_task")
def send_email_task(self, to_email: str, subject: str, body: str, is_html: bool = True):
    """
    Send email asynchronously. Runs with Flask app context (ContextTask).
    """
    try:
        from flask_mail import Message
        msg = Message(subject=subject, body=body or "", recipients=[to_email])
        if is_html:
            msg.html = body or ""
        mail.send(msg)
        return True
    except Exception as e:
        logger.exception("send_email_task failed for %s: %s", to_email, e)
        return False
