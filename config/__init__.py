"""
Configuration Module

This module provides centralized configuration management for the application.
"""

from .settings import (
    Config,
    DevelopmentConfig,
    ProductionConfig,
    StagingConfig,
    current_environment,
)
from .constants import *

__all__ = [
    'Config',
    'DevelopmentConfig',
    'ProductionConfig',
    'StagingConfig',
    'get_config'
]


CONFIG_BY_ENVIRONMENT = {
    'development': DevelopmentConfig,
    'staging': StagingConfig,
    'production': ProductionConfig,
    'testing': DevelopmentConfig,  # Can create TestingConfig later
}


def get_config(env=None):
    """
    Returns the appropriate configuration object based on environment.

    Args:
        env: Environment name ('development', 'production'). If None, reads from FLASK_ENV

    Returns:
        Configuration class

    Raises:
        ValueError: the name is not one this application knows.

    **An unrecognised name raises instead of falling back to development.** It
    used to end in `config_map.get(env, DevelopmentConfig)`, so `prod`,
    `Production`, a stray space, or a variable that failed to load all selected
    development — and on a production box that is not one setting going wrong
    but five, because `ProductionConfig.init_app` never runs to object:

      * `SECRET_KEY` stays the published development literal, and
        `JWT_SECRET_KEY` inherits it, so every token is signed with it
      * CORS becomes `['*']` **with credentials**, which flask-cors serves by
        echoing the caller's own origin back
      * `DEBUG` is on
      * GraphQL introspection and the IDE are on
      * the session cookie loses `Secure`

    None of it raises, logs, or looks any different from the outside. Refusing
    to boot is the cheaper failure by a wide margin.

    Capitalisation and surrounding whitespace are normalised rather than
    rejected — `Production` is how somebody spells it, not what they meant
    differently. An unset or empty value still means development, because that
    is the ordinary local case.
    """
    import logging
    import os

    # Keep what was actually given, so a refusal can name it. Reading it from
    # the environment and then reporting `None` would be useless at 2am.
    given = os.getenv('FLASK_ENV') if env is None else env
    normalised = (
        current_environment() if env is None else str(env).strip().lower()
    ) or 'development'

    if normalised not in CONFIG_BY_ENVIRONMENT:
        known = ', '.join(sorted(CONFIG_BY_ENVIRONMENT))
        raise ValueError(
            f"Unknown FLASK_ENV {given!r}. Expected one of: {known}. "
            "Refusing to start rather than silently running the development "
            "configuration, which would publish the development secret key, "
            "enable CORS for any origin with credentials, turn on DEBUG and "
            "GraphQL introspection, and drop Secure from the session cookie."
        )

    if normalised == 'development' and not os.getenv('FLASK_ENV'):
        # Ordinary locally; on a server it means the variable never arrived.
        logging.getLogger(__name__).warning(
            "FLASK_ENV is not set — defaulting to the development "
            "configuration. Set FLASK_ENV=production on a deployed instance."
        )

    return CONFIG_BY_ENVIRONMENT[normalised]
