"""Markdown processing.

Provides abstraction for markdown rendering using the Python markdown library.
"""

from pathlib import Path

import markdown


class MarkdownProcessor:
    """Markdown processor using the Python markdown library."""

    def __init__(self, scriptdir: Path):
        """Initialize markdown processor.

        Args:
            scriptdir: Unused; kept for interface compatibility.
        """
        self.available = True

    def render(self, text: str) -> str:
        """Render markdown text to HTML.

        Args:
            text: Markdown text.

        Returns:
            Rendered HTML.
        """
        return markdown.markdown(text, output_format="html")
