"""Per-post text background (#15) and caption file names (.txt / .md)."""

import pytest

from tests.conftest import make_generator, make_test_image

STYLE = 'style="background-color: rgba(0,0,0,.5); padding: 0.5em 1em"'


def page(topdir, captions, theme="theme1", gallery_metadata=None):
    """Build a one-gallery site; ``captions`` maps photo stem -> caption file text (or None)."""
    g = topdir / "g"
    g.mkdir()
    for i, (stem, caption) in enumerate(captions.items(), 1):
        make_test_image(g / f"{i:02d} {stem}.jpg", 1200, 900, "red")
        if caption is not None:
            (g / f"{i:02d} {stem}.txt").write_text(caption, encoding="utf-8")
    if gallery_metadata:
        (g / "metadata.txt").write_text(gallery_metadata, encoding="utf-8")
    gen = make_generator(topdir, config_overrides={"theme_dir": theme})
    gen.scan_directories()
    gen.read_files()
    gen.build_html()
    gen.cleanup()
    return (topdir / "_site" / "g" / "index.html").read_text(encoding="utf-8")


class TestTextBackground:
    def test_theme1_post_with_background(self, tmp_path):
        html = page(tmp_path, {"a": "textbackground: rgba(0,0,0,.5)\n---\nHello"})
        assert f'<div class="content" {STYLE}>' in html

    def test_theme2_post_with_background(self, tmp_path):
        html = page(tmp_path, {"a": "textbackground: rgba(0,0,0,.5)\n---\nHello"}, theme="theme2")
        assert f'<div class="post index1" {STYLE}>' in html

    @pytest.mark.parametrize(
        "theme,element",
        [("theme1", '<div class="content">'), ("theme2", '<div class="post index1">')],
    )
    def test_unset_leaves_markup_identical(self, tmp_path, theme, element):
        """Without the key, the caption element is exactly the original expose.sh markup."""
        html = page(tmp_path, {"a": "Hello"}, theme=theme)
        assert element in html
        assert "textbackground" not in html
        assert "padding: 0.5em 1em" not in html

    def test_gallery_wide_and_post_override(self, tmp_path):
        html = page(
            tmp_path,
            {"a": "Plain", "b": "textbackground: #ff0000\n---\nRed"},
            gallery_metadata="textbackground: rgba(0,0,0,.5)\n",
        )
        assert html.count(STYLE) == 1  # "a" inherits the gallery value
        assert 'style="background-color: #ff0000; padding: 0.5em 1em"' in html  # "b" overrides

    @pytest.mark.parametrize(
        "value", ['red" onclick="x', "red; position: fixed", "</div><script>", "url(x) {"]
    )
    def test_unsafe_values_are_ignored(self, tmp_path, capsys, value):
        html = page(tmp_path, {"a": f"textbackground: {value}\n---\nHello"})
        assert '<div class="content">' in html
        assert value not in html  # (the theme has its own onclick/<script>, so check the value)
        assert "Ignoring textbackground" in capsys.readouterr().out


class TestCaptionFiles:
    def test_markdown_caption_file(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        make_test_image(g / "photo.jpg", 1200, 900, "red")
        (g / "photo.md").write_text("A *markdown* caption", encoding="utf-8")
        gen = make_generator(tmp_path)
        gen.scan_directories()
        gen.read_files()
        gen.build_html()
        html = (tmp_path / "_site" / "g" / "index.html").read_text(encoding="utf-8")
        assert "A <em>markdown</em> caption" in html
        gen.cleanup()

    def test_txt_wins_over_md(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        make_test_image(g / "photo.jpg", 1200, 900, "red")
        (g / "photo.txt").write_text("from txt", encoding="utf-8")
        (g / "photo.md").write_text("from md", encoding="utf-8")
        gen = make_generator(tmp_path)
        gen.scan_directories()
        gen.read_files()
        gen.build_html()
        html = (tmp_path / "_site" / "g" / "index.html").read_text(encoding="utf-8")
        assert "from txt" in html and "from md" not in html
        gen.cleanup()
