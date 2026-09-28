"""Markdown captions with YAML front matter (#52), and converting .txt captions to them."""

import pytest
from click.testing import CliRunner

from dorothea.captions import parse_caption
from dorothea.check import check_site
from dorothea.cli import main
from dorothea.config import DEFAULT_CONFIG, Config
from dorothea.convert import caption_to_markdown
from tests.conftest import make_generator, make_test_image


class TestFrontMatter:
    def test_read_as_yaml(self):
        caption = parse_caption(
            '---\ntitle: "Falls: day 1"\ntextcolor: "#ff9518"\ntop: 30\n# lens: Helios\n---\n'
            "The **falls**.\n\nMore.\n",
            "01 falls.md",
        )
        assert caption.front_matter
        assert caption.values == {"title": "Falls: day 1", "textcolor": "#ff9518", "top": "30"}
        assert caption.body == "The **falls**.\n\nMore."
        assert caption.lines == {"title": 2, "textcolor": 3, "top": 4}
        assert caption.warnings == []

    def test_lists_and_multi_line_values(self):
        caption = parse_caption(
            "---\npolygon: [{x: 5, y: 0}, {x: 100, y: 100}]\ndescription: |\n  a\n  b\n---\n",
            "a.md",
        )
        assert caption.values["polygon"] == '[{"x": 5, "y": 0}, {"x": 100, "y": 100}]'
        assert caption.values["description"] == "a\nb"
        assert "description: a b" in caption.head  # one line for templates

    @pytest.mark.parametrize(
        "text,name",
        [
            ("---\ntitle: T\n---\nx", "a.txt"),  # .txt: always line by line
            ("title: T\n---\nx", "a.md"),  # no opening ---: expose.sh style
            ("x\n", "a.md"),  # no metadata at all
        ],
    )
    def test_line_by_line_otherwise(self, text, name):
        assert not parse_caption(text, name).front_matter

    def test_legacy_reads_everything_line_by_line(self):
        caption = parse_caption('---\ntextcolor: "#fff"\n---\nx', "a.md", front_matter=False)
        assert not caption.front_matter
        assert caption.values == {"textcolor": '"#fff"'}  # as expose.sh would

    def test_crlf_and_bom(self):
        caption = parse_caption("﻿---\r\ntitle: T\r\n---\r\nx\r\n", "a.md")
        assert caption.front_matter and caption.values == {"title": "T"} and caption.body == "x"


class TestFallback:
    """expose.sh-style lines in front matter: read the old way, with a warning saying why."""

    def test_unquoted_colour(self):
        caption = parse_caption("---\ntitle: T\ntextcolor: #ff9518\n---\nx", "a.md")
        assert not caption.front_matter
        assert caption.values == {"title": "T", "textcolor": "#ff9518"}  # nothing lost
        assert caption.warning_lines("a.md") == [
            "a.md line 3: 'textcolor: #ff9518' reads as empty in YAML; quote the value: "
            'textcolor: "#ff9518"',
            "a.md: read line by line (as a .txt caption) until that's fixed",
        ]

    @pytest.mark.parametrize("line", ['polygon:[{"x":5, "y":0}]', "title: Iceland: day 1"])
    def test_not_valid_yaml(self, line):
        caption = parse_caption(f"---\n{line}\n---\nx", "a.md")
        assert not caption.front_matter
        assert caption.body == "x"
        assert "not valid YAML" in caption.warning_lines("a.md")[0]

    def test_every_dropped_value_is_reported(self):
        caption = parse_caption("---\ntextcolor: #fff\ncolor1: #000\n---\nx", "a.md")
        assert [line for line, _ in caption.warnings] == [2, 3, None]


def build(root, files, legacy=False):
    g = root / "g"
    g.mkdir(parents=True)
    make_test_image(g / "01 a.jpg", 800, 600, "red")
    for name, text in files.items():
        (g / name).write_text(text, encoding="utf-8")
    gen = make_generator(root, config_overrides={"theme_dir": "theme1", "legacy": legacy})
    gen.scan_directories()
    gen.read_files()
    gen.build_html()
    gen.cleanup()
    return (root / "_site" / "g" / "index.html").read_text(encoding="utf-8")


class TestPages:
    def test_md_front_matter_builds_the_same_page_as_txt(self, tmp_path):
        txt = build(
            tmp_path / "txt", {"01 a.txt": "top: 12\ntextcolor: #ff9518\n---\nThe *falls*."}
        )
        md = build(
            tmp_path / "md", {"01 a.md": '---\ntop: 12\ntextcolor: "#ff9518"\n---\nThe *falls*.'}
        )
        assert md == txt
        assert "top: 12%" in md and "<em>falls</em>" in md

    def test_fallback_warns_during_the_build(self, tmp_path, capsys):
        html = build(tmp_path, {"01 a.md": "---\ntextcolor: #ff9518\n---\nx"})
        out = capsys.readouterr().out
        assert "Warning: 01 a.md line 2: 'textcolor: #ff9518' reads as empty in YAML" in out
        assert "#ff9518" in html

    def test_legacy_pages_are_unchanged(self, tmp_path):
        """With --legacy the .md is read as expose.sh reads it, quotes and all."""
        html = build(tmp_path, {"01 a.md": '---\ntitle: "T"\n---\nx'}, legacy=True)
        assert "x" in html


class TestCheck:
    def site(self, root, files):
        (root / "g").mkdir(parents=True, exist_ok=True)
        make_test_image(root / "g/01 a.jpg", 64, 48, "red")
        for name, text in files.items():
            (root / "g" / name).write_text(text, encoding="utf-8")
        checker = check_site(root, Config(dict(DEFAULT_CONFIG)))
        return [p.show(root) for p in checker.problems]

    def test_front_matter_keys_with_their_lines(self, tmp_path):
        assert self.site(tmp_path, {"01 a.md": "---\ntitle: T\ntitel: x\nsort: name\n---\n"}) == [
            "g/01 a.md:3: unknown key titel; did you mean title?",
            "g/01 a.md:4: sort only works for a whole gallery: put it in gallery.yml",
        ]

    def test_fallback_is_a_problem(self, tmp_path):
        found = self.site(tmp_path, {"01 a.md": "---\ntextcolor: #fff\n---\n"})
        assert found[0].startswith("g/01 a.md:2: 'textcolor: #fff' reads as empty in YAML")

    def test_txt_and_md_for_the_same_photo(self, tmp_path):
        assert self.site(tmp_path, {"01 a.txt": "x", "01 a.md": "y"}) == [
            "g/01 a.txt: not used: 01 a.md is read instead"
        ]

    def test_legacy_reads_the_txt(self, tmp_path):
        (tmp_path / "g").mkdir()
        make_test_image(tmp_path / "g/01 a.jpg", 64, 48, "red")
        (tmp_path / "g/01 a.txt").write_text("x")
        (tmp_path / "g/01 a.md").write_text("y")
        checker = check_site(tmp_path, Config({**DEFAULT_CONFIG, "legacy": True}))
        assert [p.show(tmp_path) for p in checker.problems] == [
            "g/01 a.md: not used: 01 a.txt is read instead"
        ]


class TestConvert:
    def test_caption_to_markdown(self):
        assert caption_to_markdown(
            'Stray\n---\ntitle: T\ntextcolor: #fff\npolygon:[{"x":5}]\n---\nThe *falls*.\n'
        ) == (
            "---\n# Stray\ntitle: T\ntextcolor: '#fff'\npolygon: '[{\"x\":5}]'\n---\nThe *falls*.\n"
        )

    def test_caption_without_metadata_is_unchanged(self):
        assert caption_to_markdown("Just words.\r\n") == "Just words.\n"

    def test_only_separators(self):
        assert caption_to_markdown("---\n---\nx") == "---\n---\nx\n"

    def run(self, root, monkeypatch):
        monkeypatch.chdir(root)
        return CliRunner().invoke(main, ["--convert-config"], prog_name="dorothea")

    def test_converts_captions_and_keeps_pages(self, tmp_path, monkeypatch):
        files = {
            "01 a.txt": 'top: 12\ntextcolor: #ff9518\npolygon:[{"x":5, "y":0}]\n---\nThe *falls*.'
        }
        before = build(tmp_path / "before", files)
        site = tmp_path / "site"
        build(site, files)
        result = self.run(site, monkeypatch)
        assert result.exit_code == 0, result.output
        assert "Wrote 1 .md caption(s) (from .txt, now deleted)" in result.output
        assert not (site / "g/01 a.txt").exists()
        gen = make_generator(site, config_overrides={"theme_dir": "theme1"})
        gen.scan_directories()
        gen.read_files()
        gen.build_html()
        gen.cleanup()
        assert (site / "_site/g/index.html").read_text(encoding="utf-8") == before

    def test_leaves_non_captions_and_existing_md(self, tmp_path, monkeypatch):
        (tmp_path / "g").mkdir()
        make_test_image(tmp_path / "g/01 a.jpg", 64, 48, "red")
        (tmp_path / "g/01 a.txt").write_text("title: T\n---\nx")
        (tmp_path / "g/01 a.md").write_text("mine")
        (tmp_path / "g/notes.txt").write_text("notes")
        result = self.run(tmp_path, monkeypatch)
        assert "g/01 a.txt: left as it is; 01 a.md already exists" in result.stderr
        assert (tmp_path / "g/notes.txt").exists() and (tmp_path / "g/01 a.txt").exists()

    def test_legacy_sites_keep_their_txt_captions(self, tmp_path, monkeypatch):
        (tmp_path / "g").mkdir()
        make_test_image(tmp_path / "g/01 a.jpg", 64, 48, "red")
        (tmp_path / "g/01 a.txt").write_text("title: T\n---\nx")
        (tmp_path / "_config.yml").write_text("legacy: true\n")
        result = self.run(tmp_path, monkeypatch)
        assert "legacy: true" in result.stderr
        assert (tmp_path / "g/01 a.txt").exists()
