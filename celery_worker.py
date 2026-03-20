"""
Celery worker entry point. Use this to avoid circular imports with backend.app.

Worker: celery -A backend.celery_worker:celery worker -l info
Beat:   celery -A backend.celery_worker:celery beat -l info
"""

from backend.app import create_app
from backend.celery_app import init_celery, get_celery

app = create_app()
celery = init_celery(app)
