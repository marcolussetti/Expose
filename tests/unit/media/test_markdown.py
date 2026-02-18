"""Unit tests for pyexpose.media.markdown module.

Tests the MarkdownProcessor class.
"""

from pathlib import Path

import pytest
from pyexpose.media.markdown import MarkdownProcessor


@pytest.fixture
def markdown_processor(tmp_path):
    """Create a MarkdownProcessor instance."""
    return MarkdownProcessor(tmp_path)


class TestMarkdownProcessor:
    """Test MarkdownProcessor methods."""

    def test_always_available(self, tmp_path):
        """Processor is always available (no external deps)."""
        processor = MarkdownProcessor(tmp_path)
        assert processor.available is True

    def test_render_basic_markdown(self, tmp_path):
        """Test rendering basic markdown."""
        processor = MarkdownProcessor(tmp_path)
        result = processor.render("**bold** and *italic*")
        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result

    def test_render_paragraph(self, tmp_path):
        """Test rendering paragraph."""
        processor = MarkdownProcessor(tmp_path)
        result = processor.render("This is a paragraph.")
        assert "<p>" in result
        assert "This is a paragraph." in result

    def test_render_heading(self, tmp_path):
        """Test rendering heading."""
        processor = MarkdownProcessor(tmp_path)
        result = processor.render("# Heading 1")
        assert "<h1>" in result
        assert "Heading 1" in result

    def test_scriptdir_ignored(self):
        """scriptdir param is accepted but unused."""
        processor = MarkdownProcessor(Path("/nonexistent/path"))
        assert processor.available is True
        result = processor.render("hello")
        assert "hello" in result
