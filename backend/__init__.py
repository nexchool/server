"""
Backend package wrapper.

The codebase historically references modules under `backend.*`, but the actual
implementation lives directly in the `server/` directory (e.g. `server/core`,
`server/modules`, `server/config`).

This package exists so Flask/Gunicorn/Celery imports like `backend.app:app`
work correctly without rewriting the backend.
"""

