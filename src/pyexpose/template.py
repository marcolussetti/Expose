"""Template engine for PyExpose.

Provides sed-like template substitution to maintain parity with
the original shell script implementation.
"""

import re


class TemplateEngine:
    """Sed-like template substitution engine.

    Provides template substitution that exactly matches the behavior
    of the original shell script's sed-based templating.

    Template syntax:
        {{key}} - replaced with value
        {{key:default}} - replaced with value, or default if key not set
    """

    @staticmethod
    def substitute(text: str, key: str, value: str) -> str:
        """Replace {{key}} and {{key:default}} with value.

        Note: Whitespace is collapsed to match shell's unquoted echo $value.

        Args:
            text: Template text.
            key: Template variable name.
            value: Replacement value.

        Returns:
            Text with substitutions applied.
        """
        key = key.strip()
        # Collapse whitespace like shell's unquoted echo $value
        collapsed_value = " ".join(value.split())

        # Use a lambda to avoid regex escape sequence issues
        def replacer(match):
            return collapsed_value

        # Replace {{key}} and {{key:default}}
        text = re.sub(r"\{\{" + re.escape(key) + r"\}\}", replacer, text)
        text = re.sub(r"\{\{" + re.escape(key) + r":[^}]*\}\}", replacer, text)

        return text

    @staticmethod
    def apply_defaults(text: str) -> str:
        """Apply default values for {{key:default}} patterns.

        Args:
            text: Template text.

        Returns:
            Text with defaults applied.
        """

        # Find all {{key:default}} patterns and replace with default
        def replace_with_default(match):
            return match.group(1)

        text = re.sub(r"\{\{[^:}]+:([^}]*)\}\}", replace_with_default, text)
        return text

    @staticmethod
    def clean_unused(text: str) -> str:
        """Remove unused {{key}} variables.

        Args:
            text: Template text.

        Returns:
            Text with unused variables removed.
        """
        # Remove any remaining {{key}} patterns
        text = re.sub(r"\{\{[^}]+\}\}", "", text)
        return text
