"""Field limits for department create/update payloads."""

NAME_MAX_LENGTH = 100
CODE_MAX_LENGTH = 20
TYPE_MAX_LENGTH = 32

SORTABLE_COLUMNS = ("display_order", "name", "created_at")
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100
