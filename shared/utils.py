"""
Shared Utility Functions

Common utility functions used throughout the application.
"""

import uuid
from datetime import datetime
from typing import Dict, Any, List


def generate_uuid() -> str:
    """Generate a UUID string"""
    return str(uuid.uuid4())


def get_timestamp() -> datetime:
    """Get current UTC timestamp"""
    return datetime.utcnow()


def paginate_query(query, page: int = 1, per_page: int = 20, max_per_page: int = 100) -> Dict[str, Any]:
    """
    Paginate a SQLAlchemy query.
    
    Args:
        query: SQLAlchemy query object
        page: Page number (1-indexed)
        per_page: Items per page
        max_per_page: Maximum allowed items per page
        
    Returns:
        Dict with paginated data and metadata
        
    Example:
        >>> from backend.modules.auth.models import User
        >>> query = User.query.filter_by(email_verified=True)
        >>> result = paginate_query(query, page=1, per_page=20)
        >>> print(result['items'])  # List of users
        >>> print(result['total'])  # Total count
    """
    # Ensure per_page doesn't exceed max
    per_page = min(per_page, max_per_page)
    
    # Calculate offset
    offset = (page - 1) * per_page
    
    # Get total count
    total = query.count()
    
    # Get items for current page
    items = query.limit(per_page).offset(offset).all()
    
    # Calculate total pages
    total_pages = (total + per_page - 1) // per_page if total > 0 else 0
    
    return {
        'items': items,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages,
    }


def format_validation_error(errors: Dict[str, List[str]]) -> Dict[str, Any]:
    """
    Format validation errors in a consistent structure.
    
    Args:
        errors: Dictionary of field names to error messages
        
    Returns:
        Formatted error response
        
    Example:
        >>> errors = {'email': ['Email is required'], 'password': ['Too short']}
        >>> format_validation_error(errors)
        {'error': 'Validation error', 'details': {...}}
    """
    return {
        'error': 'Validation error',
        'details': errors
    }


def serialize_datetime(dt: datetime) -> str:
    """
    Serialize datetime object to ISO format string.
    
    Args:
        dt: Datetime object
        
    Returns:
        ISO format string
    """
    if dt is None:
        return None
    return dt.isoformat()


def chunks(lst: List, n: int):
    """
    Yield successive n-sized chunks from list.
    
    Args:
        lst: List to chunk
        n: Chunk size
        
    Yields:
        Chunks of the list
        
    Example:
        >>> for chunk in chunks([1,2,3,4,5], 2):
        ...     print(chunk)
        [1, 2]
        [3, 4]
        [5]
    """
    for i in range(0, len(lst), n):
        yield lst[i:i + n]
