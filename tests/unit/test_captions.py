"""Caption files: metadata/caption split and the mistakes that used to fail silently (#17)."""

import re

import pytest

from dorothea.builder import split_caption
from tests.conftest import make_generator, make_test_image


class TestSplitCaption:
    def test_well_formed(self):
        meta, caption, ignored = split_caption("---\ntitle: Peak\ntop: 60\n---\nA *peak*.\n")
        assert meta == "---\ntitle: Peak\ntop: 60\n---"
        assert caption == "A *peak*."
        assert ignored == []

    def test_single_separator(self):
        meta, caption, ignored = split_caption("title: Peak\n---\nA peak.")
        assert (meta, caption, ignored) == ("title: Peak\n---", "A peak.", [])

    def test_no_metadata(self):
        assert split_caption("Just a caption.\n\nTwo paragraphs.\n") == (
            "",
            "Just a caption.\n\nTwo paragraphs.",
            [],
        )

    def test_text_before_the_metadata_block(self):
        """Upstream Jack000/Expose#46's layout: the text is dropped, now with a warning."""
        meta, caption, ignored = split_caption(
            "A train crossing the bridge.\n---\ntitle: Train\n---\n"
        )
        assert caption == ""
        assert "title: Train" in meta
        assert ignored == ["A train crossing the bridge."]

    def test_separators_with_trailing_whitespace(self):
        meta, caption, ignored = split_caption("--- \ntitle: Peak\n---\t\nA peak.")
        assert "title: Peak" in meta
        assert caption == "A peak."  # the metadata no longer leaks into the caption
        assert ignored == []

    def test_crlf(self):
        meta, caption, ignored = split_caption("---\r\ntitle: Peak\r\n---\r\nA peak.\r\n")
        assert (meta, caption, ignored) == ("---\ntitle: Peak\n---", "A peak.", [])

    def test_bom(self):
        meta, caption, ignored = split_caption("﻿---\ntitle: Peak\n---\nA peak.")
        assert "title: Peak" in meta
        assert caption == "A peak."
        assert ignored == []

    @pytest.mark.parametrize(
        "line",
        [
            "title: Peak",
            "image-options: -negate",
            "color1:#ff0000",
            'polygon:[{"x":5, "y":0}]',
            "textcolor: #ffffff",
            "  indented: yes",
            "",
        ],
    )
    def test_metadata_lines_are_not_reported(self, line):
        assert split_caption(f"---\n{line}\n---\ncaption")[2] == []

    def test_separator_needs_three_dashes_alone(self):
        """'----' or '--- text' are caption text (Markdown rules), not separators."""
        assert split_caption("Intro\n\n---- \nmore")[0] == ""
        assert split_caption("--- not a separator\ntext")[0] == ""


class TestBuiltPages:
    def _build(self, tmp_path, caption: str | bytes):
        gallery = tmp_path / "g"
        gallery.mkdir()
        make_test_image(gallery / "photo.jpg", 64, 48, "blue")
        textfile = gallery / "photo.txt"
        if isinstance(caption, bytes):
            textfile.write_bytes(caption)
        else:
            textfile.write_text(caption, encoding="utf-8")
        gen = make_generator(tmp_path)
        gen.scan_directories()
        gen.read_files()
        gen.build_html()
        return (tmp_path / "_site" / "g" / "index.html").read_text(encoding="utf-8")

    def test_warns_about_text_before_the_metadata(self, tmp_path, capsys):
        html = self._build(tmp_path, "A train crossing.\n---\ntop: 60\n---\n")
        out = capsys.readouterr().out
        assert "photo.txt: ignoring 1 line(s)" in out
        assert "'A train crossing.'" in out
        assert "after the second '---'" in out
        assert "A train crossing." not in html

    def test_trailing_spaces_keep_metadata_out_of_the_caption(self, tmp_path, capsys):
        html = self._build(tmp_path, "--- \ntitle: Secret\ntextcolor: #123456\n---  \nHello.\n")
        assert "Hello." in html
        assert "title: Secret" not in html
        assert "#123456" in html  # still applied as metadata
        assert "Warning" not in capsys.readouterr().out

    def test_crlf_and_bom(self, tmp_path, capsys):
        html = self._build(tmp_path, b"\xef\xbb\xbf---\r\ntextcolor: #123456\r\n---\r\nHello.\r\n")
        assert "#123456" in html
        assert re.search(r"<p>Hello\.</p>", html)
        assert "textcolor:" not in html
        assert "Warning" not in capsys.readouterr().out

    def test_well_formed_file_prints_nothing(self, tmp_path, capsys):
        self._build(tmp_path, "---\ntop: 60\n---\nHello.\n")
        assert "Warning" not in capsys.readouterr().out
