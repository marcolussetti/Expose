"""Markdown processing.

Renders captions with the Python markdown library, then normalizes the few places where its
HTML differs from expose.sh's Markdown.pl (``--html4tags``) so generated pages stay
byte-identical after the template engine's whitespace collapsing.
"""

import re
from pathlib import Path

import markdown

# python-markdown image tags: alt first (bare ``alt`` when the text is literally "alt"),
# then src, then an optional title. User-written inline <img> HTML rarely has this shape.
_PY_IMG = re.compile(r'<img alt(?:="([^"]*)")? src="([^"]*)"(?: title="([^"]*)")?>')
# Code spans/blocks, where both renderers escape ">" identically
_CODE = re.compile(r"(<pre>.*?</pre>|<code>.*?</code>)", re.DOTALL)


def _markdown_pl_img(match: re.Match) -> str:
    alt = "alt" if match.group(1) is None else match.group(1)
    title = match.group(3) or ""
    return f'<img src="{match.group(2)}" alt="{alt}" title="{title}">'


def normalize_to_markdown_pl(rendered: str) -> str:
    """Rewrite python-markdown output into Markdown.pl's form where they differ.

    Differences handled (all invisible in a browser):
    - loose list items: ``<li>\\n<p>…</p>\\n</li>`` → ``<li><p>…</p></li>``
    - nested lists: ``a<ul>`` → ``a\\n<ul>`` and ``</ul>\\n</li>`` → ``</ul></li>``
    - hard line breaks: ``text<br>`` → ``text <br>``
    - images: ``<img alt src title>`` → ``<img src alt title="">``
    - ``>`` in text is left unescaped (Markdown.pl only escapes it inside code)
    """
    out = re.sub(r"<li>\s*<p>", "<li><p>", rendered)
    out = re.sub(r"</p>\s*</li>", "</p></li>", out)
    out = re.sub(r"(</[uo]l>)\s*</li>", r"\1</li>", out)
    out = re.sub(r"([^>\s])(<[uo]l>)", r"\1\n\2", out)
    out = re.sub(r"(\S)<br>\n", r"\1 <br>\n", out)
    out = _PY_IMG.sub(_markdown_pl_img, out)
    parts = _CODE.split(out)
    for i in range(0, len(parts), 2):  # even indexes are outside code
        parts[i] = parts[i].replace("&gt;", ">")
    return "".join(parts)


class MarkdownProcessor:
    """Markdown processor using the Python markdown library."""

    def __init__(self, scriptdir: Path | None = None):
        """Initialize markdown processor.

        Args:
            scriptdir: Unused; kept for interface compatibility.
        """
        self.available = True

    def render(self, text: str) -> str:
        """Render markdown text to HTML matching Markdown.pl.

        Args:
            text: Markdown text.

        Returns:
            Rendered HTML.
        """
        return normalize_to_markdown_pl(markdown.markdown(text, output_format="html"))
