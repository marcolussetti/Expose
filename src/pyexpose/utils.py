"""Utility functions for PyExpose.

Pure utility functions with no external dependencies.
"""

import re


def url_safe(name: str) -> str:
    """Convert name to URL-safe format.

    Matches: sed 's/[^ a-zA-Z0-9]//g;s/ /-/g' | tr '[:upper:]' '[:lower:]'

    Args:
        name: Input name.

    Returns:
        URL-safe name (lowercase, alphanumeric and hyphens only).

    Examples:
        >>> url_safe("My Photos")
        'my-photos'
        >>> url_safe("01 Nature & Wildlife")
        '01-nature--wildlife'
    """
    # Remove non-alphanumeric chars except space
    result = re.sub(r"[^ a-zA-Z0-9]", "", name)
    # Replace spaces with hyphens
    result = result.replace(" ", "-")
    # Convert to lowercase
    return result.lower()


def strip_numeric_prefix(name: str) -> str:
    """Strip numeric prefix from name.

    Matches: sed -e 's/^[0-9]*//' | sed -e 's/^[[:space:]]*//;s/[[:space:]]*$//'

    Args:
        name: Input name.

    Returns:
        Name with numeric prefix removed and whitespace stripped.

    Examples:
        >>> strip_numeric_prefix("01 Mountains")
        'Mountains'
        >>> strip_numeric_prefix("123abc")
        'abc'
        >>> strip_numeric_prefix("  456  ")
        ''
    """
    result = re.sub(r"^[0-9]*", "", name).strip()
    return result if result else name
