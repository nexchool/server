"""Client-safe error handling for service ``except`` blocks.

Returning ``str(exception)`` to the client leaks internal details — raw SQL,
column names, record IDs, ORM internals. Use :func:`safe_error` inside service
``except`` blocks instead: it logs the real exception (with traceback) for
debugging and returns a generic, client-safe message.

    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}
"""
import logging

logger = logging.getLogger("nexchool.service_errors")

DEFAULT_MESSAGE = "Something went wrong. Please try again."


def safe_error(exc: Exception, message: str = DEFAULT_MESSAGE) -> str:
    """Log ``exc`` with its traceback and return a client-safe ``message``.

    The traceback in the log identifies exactly where it happened, so callers
    don't need to pass a label.
    """
    logger.exception("service error: %s", exc)
    return message
