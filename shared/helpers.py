"""
Shared Helper Functions

Helper functions for common operations.
"""

from flask import jsonify, make_response
from typing import Any, Dict, Tuple


def success_response(data: Any = None, message: str = None, status_code: int = 200) -> Tuple:
    """
    Create a standardized success response.
    
    Args:
        data: Response data
        message: Success message
        status_code: HTTP status code
        
    Returns:
        Flask response tuple (response, status_code)
        
    Example:
        >>> return success_response({'user': user_data}, 'User created', 201)
    """
    response = {'success': True}
    
    if message:
        response['message'] = message
    
    if data is not None:
        response['data'] = data
    
    return jsonify(response), status_code


def error_response(error: str, message: str = None, status_code: int = 400, details: Dict = None) -> Tuple:
    """
    Create a standardized error response.
    
    Args:
        error: Error type/name
        message: Detailed error message
        status_code: HTTP status code
        details: Additional error details
        
    Returns:
        Flask response tuple (response, status_code)
        
    Example:
        >>> return error_response('ValidationError', 'Email is required', 400)
    """
    response = {
        'success': False,
        'error': error
    }
    
    if message:
        response['message'] = message
    
    if details:
        response['details'] = details
    
    return jsonify(response), status_code


def not_found_response(resource: str = 'Resource') -> Tuple:
    """
    Create a standardized 404 response.
    
    Args:
        resource: Name of the resource that wasn't found
        
    Returns:
        Flask response tuple (response, status_code)
    """
    return error_response(
        error='NotFound',
        message=f'{resource} not found',
        status_code=404
    )


def unauthorized_response(message: str = 'Unauthorized') -> Tuple:
    """
    Create a standardized 401 response.
    
    Args:
        message: Unauthorized message
        
    Returns:
        Flask response tuple (response, status_code)
    """
    return error_response(
        error='Unauthorized',
        message=message,
        status_code=401
    )


def forbidden_response(message: str = 'Forbidden') -> Tuple:
    """
    Create a standardized 403 response.
    
    Args:
        message: Forbidden message
        
    Returns:
        Flask response tuple (response, status_code)
    """
    return error_response(
        error='Forbidden',
        message=message,
        status_code=403
    )


def validation_error_response(details: Dict) -> Tuple:
    """
    Create a standardized validation error response.
    
    Args:
        details: Dictionary of validation errors
        
    Returns:
        Flask response tuple (response, status_code)
    """
    return error_response(
        error='ValidationError',
        message='Validation failed',
        status_code=400,
        details=details
    )
