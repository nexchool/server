"""
Configuration Module

This module provides centralized configuration management for the application.
"""

from .settings import Config, DevelopmentConfig, ProductionConfig, StagingConfig
from .constants import *

__all__ = [
    'Config',
    'DevelopmentConfig',
    'ProductionConfig',
    'StagingConfig',
    'get_config'
]


def get_config(env=None):
    """
    Returns the appropriate configuration object based on environment.
    
    Args:
        env: Environment name ('development', 'production'). If None, reads from FLASK_ENV
        
    Returns:
        Configuration class instance
    """
    import os
    if env is None:
        env = os.getenv('FLASK_ENV', 'development')
    
    config_map = {
        'development': DevelopmentConfig,
        'staging': StagingConfig,
        'production': ProductionConfig,
        'testing': DevelopmentConfig,  # Can create TestingConfig later
    }
    
    return config_map.get(env, DevelopmentConfig)
