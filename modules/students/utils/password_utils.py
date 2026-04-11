"""Default password generation for bulk student import."""

import re


def default_student_import_password(full_name: str) -> str:
    """
    Pattern: first name token, letters only, lowercased + '@123'.
    Example: "Rahul Patel" -> "rahul@123"
    """
    if not full_name or not str(full_name).strip():
        return "student@123"
    first = str(full_name).strip().split()[0]
    letters = "".join(c for c in first.lower() if c.isalpha())
    if not letters:
        letters = "student"
    return f"{letters}@123"
