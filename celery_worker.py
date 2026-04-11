"""
Celery worker entry point. Imports app factory and Celery from sibling modules.

Worker: celery -A celery_worker:celery worker -l info
Beat:   celery -A celery_worker:celery beat -l info
"""

from app import create_app
from celery_app import init_celery, get_celery

app = create_app()
celery = init_celery(app)
