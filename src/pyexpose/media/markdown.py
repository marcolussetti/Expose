"""Markdown processing.

Provides abstraction for markdown rendering. Currently uses Perl Markdown.pl,
can be replaced with Python markdown libraries later.
"""

import shutil
import subprocess
from pathlib import Path


class MarkdownProcessor:
    """Markdown processor.

    Currently wraps Perl Markdown.pl for parity with original implementation.
    Can be replaced with Python markdown library (e.g., markdown, mistune) later.
    """

    def __init__(self, scriptdir: Path):
        """Initialize markdown processor.

        Args:
            scriptdir: Script directory where Markdown.pl is located.
        """
        self.scriptdir = Path(scriptdir)
        self.markdown_script = self.scriptdir / "Markdown_1.0.1" / "Markdown.pl"
        self.available = shutil.which("perl") is not None and self.markdown_script.exists()

    def render(self, text: str) -> str:
        """Render markdown text to HTML.

        Args:
            text: Markdown text.

        Returns:
            Rendered HTML. Returns original text if markdown not available.
        """
        if not self.available:
            return text

        result = subprocess.run(
            ["perl", str(self.markdown_script), "--html4tags"],
            input=text,
            capture_output=True,
            text=True,
        )

        return result.stdout if result.returncode == 0 else text
