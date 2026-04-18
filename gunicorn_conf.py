"""
Gunicorn configuration for School ERP backend.

Run from the app/ directory:
    gunicorn -c gunicorn_conf.py "app:app"

On macOS (with Conda/Anaconda), set before running:
    export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
"""
import os

# Render sets `PORT`; Docker Compose/local can set `GUNICORN_BIND` or `PORT`.
# Gunicorn accepts a single bind string like `0.0.0.0:5001`.
_port = os.getenv("PORT") or os.getenv("GUNICORN_PORT") or "5001"
bind = os.getenv("GUNICORN_BIND", f"0.0.0.0:{_port}")
# Low-resource hosts: WEB_CONCURRENCY / GUNICORN_WORKERS (default 4 for local dev)
_workers = os.getenv("GUNICORN_WORKERS") or os.getenv("WEB_CONCURRENCY")
workers = int(_workers) if _workers else 4
# Default to a threaded worker so long-lived SSE requests do not monopolize sync workers.
threads = int(os.getenv("GUNICORN_THREADS", "2"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
# Use gthread when threads>1 so --threads is honored (sync worker ignores threads)
worker_class = "gthread" if threads > 1 else "sync"
keepalive = 5
preload = False  # Set True to load app before forking (can help on macOS)

# When GUNICORN_RELOAD=1, restart workers on code changes (bind-mounted /app in Docker).
# Without reload or restart, new routes can 404 until workers load the new code.
reload = os.getenv("GUNICORN_RELOAD", "").strip().lower() in ("1", "true", "yes")

# Log requests to terminal (like Flask dev server)
accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s - - [%(t)s] "%(r)s" %(s)s -'
