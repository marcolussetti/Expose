"""gallery.yml, metadata.txt and # comments in metadata (#46)."""

import pytest

from dorothea.album import album_enabled
from dorothea.captions import (
    as_text,
    gallery_file,
    gallery_metadata,
    gallery_metadata_text,
    metadata_values,
    split_caption,
)
from tests.conftest import make_generator, make_test_image


class TestReading:
    def test_no_file(self, tmp_path):
        assert gallery_file(tmp_path) is None
        assert gallery_metadata(tmp_path) == {}
        assert gallery_metadata_text(tmp_path) == ""

    def test_metadata_txt_is_returned_as_it_is(self, tmp_path):
        """Pages from a metadata.txt are built exactly as before (parity)."""
        text = "width: 19\n# a comment\nclass: textafter\n"
        (tmp_path / "metadata.txt").write_text(text)
        assert gallery_metadata_text(tmp_path) == text
        assert gallery_metadata(tmp_path) == {"width": "19", "class": "textafter"}

    @pytest.mark.parametrize("name", ["gallery.yml", "gallery.yaml"])
    def test_gallery_yml_wins(self, tmp_path, name):
        (tmp_path / "metadata.txt").write_text("width: 19\n")
        (tmp_path / name).write_text("width: 32.5\n")
        assert gallery_file(tmp_path).name == name
        assert gallery_metadata(tmp_path) == {"width": "32.5"}

    def test_yaml_values_as_text(self, tmp_path):
        (tmp_path / "gallery.yml").write_text(
            "# settings for this gallery\n"
            "download: false\n"
            "date: 2022-07-14\n"
            "polygon: [{x: 5, y: 0}, {x: 100, y: 100}, {x: 0, y: 16}]\n"
            "description: |\n  Two weeks driving.\n\n  Mostly rain.\n"
            "top:\n"
        )
        assert gallery_metadata(tmp_path) == {
            "download": "false",
            "date": "2022-07-14",
            "polygon": '[{"x": 5, "y": 0}, {"x": 100, "y": 100}, {"x": 0, "y": 16}]',
            "description": "Two weeks driving.\n\nMostly rain.\n",  # Markdown keeps its lines
        }
        # for templates, one line per key
        assert "description: Two weeks driving. Mostly rain." in gallery_metadata_text(tmp_path)

    def test_broken_yaml_warns_once_and_is_empty(self, tmp_path, capsys):
        (tmp_path / "gallery.yml").write_text("sort: [name\n")
        assert gallery_metadata(tmp_path) == {}
        assert gallery_metadata(tmp_path) == {}
        out = capsys.readouterr().out
        assert out.count("ignoring") == 1 and "gallery.yml: line 2" in out

    @pytest.mark.parametrize(
        "value,text",
        [(True, "true"), (False, "false"), (3, "3"), (1.5, "1.5"), ("x", "x"), (None, ""),
         ([1, 2], "[1, 2]"), ({"a": "é"}, '{"a": "é"}')],
    )  # fmt: skip
    def test_as_text(self, value, text):
        assert as_text(value) == text

    def test_album_download_from_gallery_yml(self, tmp_path):
        (tmp_path / "gallery.yml").write_text("download: false\n")
        assert album_enabled(True, tmp_path) is False


class TestComments:
    def test_comments_are_not_metadata(self):
        assert metadata_values("# title: Old\ntitle: New\n  # indented: too\n") == {"title": "New"}

    def test_comments_are_not_caption_text_before_the_metadata(self):
        """They used to be reported as caption text put before the metadata by mistake."""
        head, caption, ignored = split_caption("# notes for me\ntitle: T\n---\nCaption\n")
        assert ignored == []
        assert caption == "Caption"


def build_page(topdir, files, theme="theme1"):
    g = topdir / "g"
    g.mkdir(parents=True)
    make_test_image(g / "01 a.jpg", 800, 600, "red")
    for name, text in files.items():
        (g / name).write_text(text, encoding="utf-8")
    gen = make_generator(topdir, config_overrides={"theme_dir": theme})
    gen.scan_directories()
    gen.read_files()
    gen.build_html()
    gen.cleanup()
    return (topdir / "_site" / "g" / "index.html").read_text(encoding="utf-8")


class TestPages:
    def test_gallery_yml_reaches_the_template(self, tmp_path):
        html = build_page(tmp_path, {"gallery.yml": "top: 12\nleft: 50\n"})
        assert "top: 12%; left: 50%" in html

    def test_polygon_from_yaml(self, tmp_path):
        html = build_page(
            tmp_path, {"gallery.yml": "polygon: [{x: 5, y: 0}, {x: 100, y: 0}, {x: 0, y: 16}]\n"}
        )
        assert (
            """data-polygon='[{"x": 5, "y": 0}, {"x": 100, "y": 0}, {"x": 0, "y": 16}]'""" in html
        )

    def test_same_page_from_metadata_txt_and_gallery_yml(self, tmp_path):
        from_txt = build_page(tmp_path / "txt", {"metadata.txt": "top: 12\nleft: 50\n"})
        from_yml = build_page(tmp_path / "yml", {"gallery.yml": "top: 12\nleft: 50\n"})
        assert from_txt == from_yml

    def test_commented_out_keys_do_nothing(self, tmp_path):
        commented = build_page(tmp_path / "a", {"01 a.txt": "# top: 12\n---\nHi\n"})
        plain = build_page(tmp_path / "b", {"01 a.txt": "---\nHi\n"})
        assert commented == plain
        assert "top: 70%" in commented  # the theme's default

    def test_gallery_sort_from_gallery_yml(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        for name in ("b.jpg", "a.jpg"):
            make_test_image(g / name, 64, 48, "red")
        (g / "gallery.yml").write_text("sort: name-desc\n")
        gen = make_generator(tmp_path)
        gen.scan_directories()
        gen.read_files()
        gen.cleanup()
        assert [f.name for f in gen.gallery_files] == ["b.jpg", "a.jpg"]
