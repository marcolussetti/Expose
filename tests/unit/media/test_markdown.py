"""Unit tests for pyexpose.media.markdown module.

Tests the MarkdownProcessor class that wraps Markdown.pl.
"""

import shutil
from pathlib import Path

import pytest
from pyexpose.media.markdown import MarkdownProcessor


@pytest.fixture
def markdown_processor(tmp_path):
    """Create a MarkdownProcessor instance."""
    # Use a path that contains Markdown.pl
    scriptdir = Path(__file__).resolve().parent.parent.parent.parent
    return MarkdownProcessor(scriptdir)


class TestMarkdownProcessor:
    """Test MarkdownProcessor methods."""

    def test_availability_check(self, markdown_processor):
        """Test that availability is correctly detected."""
        has_perl = shutil.which("perl") is not None
        has_script = markdown_processor.markdown_script.exists()

        assert markdown_processor.available == (has_perl and has_script)

    def test_render_basic_markdown(self, markdown_processor):
        """Test rendering basic markdown."""
        if not markdown_processor.available:
            pytest.skip("Markdown.pl not available")

        text = "**bold** and *italic*"
        result = markdown_processor.render(text)

        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result

    def test_render_when_unavailable(self, tmp_path):
        """Test that render returns original text when markdown unavailable."""
        # Create processor with non-existent scriptdir
        processor = MarkdownProcessor(tmp_path / "nonexistent")

        text = "**bold** text"
        result = processor.render(text)

        # Should return original text unchanged
        assert result == text

    def test_render_paragraph(self, markdown_processor):
        """Test rendering paragraph."""
        if not markdown_processor.available:
            pytest.skip("Markdown.pl not available")

        text = "This is a paragraph."
        result = markdown_processor.render(text)

        assert "<p>" in result
        assert "This is a paragraph." in result

    def test_render_heading(self, markdown_processor):
        """Test rendering heading."""
        if not markdown_processor.available:
            pytest.skip("Markdown.pl not available")

        text = "# Heading 1"
        result = markdown_processor.render(text)

        assert "<h1>" in result
        assert "Heading 1" in result
