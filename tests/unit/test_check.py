"""``dorothea check`` (#46): mistakes in gallery files and captions, with file and line."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from dorothea.check import check_site, theme_keys
from dorothea.cli import main
from dorothea.config import DEFAULT_CONFIG, Config
from dorothea.themes import BUNDLED_THEMES_DIR
from tests.conftest import make_test_image


def site(root: Path, files: dict[str, str], photos=("g/01 a.jpg",)) -> Path:
    """A gallery folder with ``photos`` (tiny JPEGs) and text ``files``."""
    for photo in photos:
        (root / photo).parent.mkdir(parents=True, exist_ok=True)
        make_test_image(root / photo, 64, 48, "red")
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def problems(root: Path, theme: str = "photoessay") -> list[str]:
    checker = check_site(root, Config({**DEFAULT_CONFIG, "theme_dir": theme}))
    return [p.show(root) for p in checker.problems]


def test_a_clean_site(tmp_path):
    site(tmp_path, {
        "g/gallery.yml": "# my trip\nsort: capture\ndate: 2022-07-14\ndownload: false\n",
        "g/01 a.txt": "title: Falls\ntop: 30\ntextbackground: rgba(0,0,0,.5)\nexif: caption\n"
                      "lens: Helios 44-2\n# polygon: [...]\n---\nCaption *here*.\n",
    })  # fmt: skip
    assert problems(tmp_path) == []


class TestKeys:
    def test_typos_suggest_a_key(self, tmp_path):
        site(tmp_path, {"g/01 a.txt": "titel: Falls\ntextbackgroud: red\n---\n"})
        assert problems(tmp_path) == [
            "g/01 a.txt:1: unknown key titel; did you mean title?",
            "g/01 a.txt:2: unknown key textbackgroud; did you mean textbackground?",
        ]

    def test_unknown_key_without_a_close_match(self, tmp_path):
        site(tmp_path, {"g/01 a.txt": "mood: happy\n---\n"})
        assert problems(tmp_path) == [
            "g/01 a.txt:1: unknown key mood (Dorothea and the theme ignore it)"
        ]

    @pytest.mark.parametrize(
        "theme,key,known",
        [("photoessay", "polygon", True), ("theme1", "top", True), ("medium", "class", True),
         ("medium", "polygon", False), ("theme2", "top", False)],
    )  # fmt: skip
    def test_keys_come_from_the_theme(self, tmp_path, theme, key, known):
        site(tmp_path, {"g/01 a.txt": f"{key}: 1\n---\n"})
        assert (problems(tmp_path, theme) == []) is known

    def test_theme_keys_are_its_post_template_placeholders(self):
        keys = theme_keys(BUNDLED_THEMES_DIR / "photoessay")
        assert {"top", "left", "width", "height", "polygon", "imageurl"} <= keys
        assert "sitetitle" not in keys  # template.html, not metadata

    def test_a_custom_theme_needs_no_declaration(self, tmp_path):
        theme = tmp_path / "_mytheme"
        theme.mkdir()
        (theme / "template.html").write_text("{{content}}")
        (theme / "post-template.html").write_text("<div class='{{mood:calm}}'>{{post}}</div>")
        site(tmp_path, {"g/01 a.txt": "mood: happy\n---\n"})
        assert problems(tmp_path, theme="_mytheme") == []

    def test_palette_keys_are_known(self, tmp_path):
        site(tmp_path, {"g/01 a.txt": "color1: #000\ntextcolor: #fff\n---\n"})
        assert problems(tmp_path) == []


class TestValues:
    @pytest.mark.parametrize(
        "line,message",
        [
            ("sort: random", "sort: 'random' must be one of name, name-desc"),
            ("date: next tuesday", "date: 'next tuesday' isn't a date Dorothea can read"),
            ("feed: maybe", "feed: 'maybe' must be true or false"),
            ("download: sometimes", "download: 'sometimes' must be true or false"),
            ("exif: maybe", "exif: 'maybe' must be false, icon or caption"),
            ("textbackground: red; x", "textbackground: 'red; x' isn't a CSS colour"),
        ],
    )
    def test_invalid_values(self, tmp_path, line, message):
        site(tmp_path, {"g/metadata.txt": f"{line}\n"})
        found = problems(tmp_path)
        assert len(found) == 1 and found[0].startswith(f"g/metadata.txt:1: {message}"), found

    @pytest.mark.parametrize(
        "line", ["feed: no", "download: On", "exif: false", "date: 2022-07-14 18:30"]
    )
    def test_valid_values(self, tmp_path, line):
        site(tmp_path, {"g/metadata.txt": f"{line}\n"})
        assert problems(tmp_path) == []

    def test_yaml_values(self, tmp_path):
        site(tmp_path, {"g/gallery.yml": "download: yes\nfeed: true\nwidth: 30\nsort: [name]\n"})
        assert problems(tmp_path) == ["g/gallery.yml:4: sort should be a single value, not a list"]


class TestPlaces:
    @pytest.mark.parametrize(
        "key", ["sort: name", "feed: false", "download: false", "description: x"]
    )
    def test_gallery_only_keys_in_a_caption(self, tmp_path, key):
        site(tmp_path, {"g/01 a.txt": f"{key}\n---\n"})
        name = key.split(":")[0]
        assert problems(tmp_path) == [
            f"g/01 a.txt:1: {name} only works for a whole gallery: put it in gallery.yml"
        ]

    def test_caption_without_a_photo(self, tmp_path):
        site(tmp_path, {"g/02 gone.txt": "Caption\n", "g/notes.md": "x"})
        assert problems(tmp_path) == [
            "g/02 gone.txt: no photo or video named 02 gone.*, so this caption isn't shown",
            "g/notes.md: no photo or video named notes.*, so this caption isn't shown",
        ]

    def test_hidden_and_underscore_files_are_skipped(self, tmp_path):
        site(tmp_path, {"g/_notes.txt": "x", "g/.hidden.txt": "x"})
        assert problems(tmp_path) == []

    def test_a_sequence_folder_can_have_a_caption(self, tmp_path):
        site(tmp_path, {"g/02 clouds imagesequence.txt": "title: Clouds\n---\n"},
             photos=("g/01 a.jpg", "g/02 clouds imagesequence/0001.jpg"))  # fmt: skip
        assert problems(tmp_path) == []

    def test_metadata_txt_next_to_gallery_yml(self, tmp_path):
        site(tmp_path, {"g/gallery.yml": "sort: name\n", "g/metadata.txt": "sort: natural\n"})
        assert problems(tmp_path) == ["g/metadata.txt: not used: gallery.yml is read instead"]

    def test_gallery_file_in_a_section(self, tmp_path):
        site(tmp_path, {"trips/metadata.txt": "sort: name\n"}, photos=("trips/g/01 a.jpg",))
        assert problems(tmp_path) == [
            "trips/metadata.txt: not used: this folder only holds other galleries"
        ]


class TestCaptions:
    def test_text_before_the_metadata(self, tmp_path):
        site(tmp_path, {"g/01 a.txt": "The falls at dawn\n---\ntitle: T\n---\nx\n"})
        assert problems(tmp_path) == [
            "g/01 a.txt:1: not shown: text before the metadata's closing '---' is read as "
            "metadata; put the caption after it"
        ]

    def test_key_set_twice(self, tmp_path):
        site(tmp_path, {"g/01 a.txt": "top: 10\nleft: 5\ntop: 20\n---\n"})
        assert problems(tmp_path) == ["g/01 a.txt:3: top is set twice; line 1's is used"]

    def test_broken_gallery_yml(self, tmp_path):
        site(tmp_path, {"g/gallery.yml": "sort: [name\n"})
        found = problems(tmp_path)
        assert (
            len(found) == 1 and "g/gallery.yml: can't be read, so it's ignored: line 2" in found[0]
        )


class TestCommand:
    def run(self, root, monkeypatch, *args):
        monkeypatch.chdir(root)
        return CliRunner().invoke(main, ["check", *args], prog_name="dorothea")

    def test_no_problems(self, tmp_path, monkeypatch):
        site(tmp_path, {"g/01 a.txt": "title: T\n---\nx\n"})
        result = self.run(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        assert "Checked the settings, 1 gallery and 1 caption: no problems found." in result.output

    def test_problems_exit_1(self, tmp_path, monkeypatch):
        site(tmp_path, {"g/01 a.txt": "titel: T\n---\n", "_config.yml": "site_titel: X\n"})
        result = self.run(tmp_path, monkeypatch)
        assert result.exit_code == 1
        assert "g/01 a.txt:1: unknown key titel; did you mean title?" in result.stdout
        assert "did you mean site_title?" in result.stderr
        assert "2 problems." in result.stdout

    def test_config_error_exits_2(self, tmp_path, monkeypatch):
        site(tmp_path, {"_config.yml": "jpeg_quality: 500\n"})
        result = self.run(tmp_path, monkeypatch)
        assert result.exit_code == 2
        assert "jpeg_quality must be an integer" in result.stderr

    def test_checks_with_the_options_given(self, tmp_path, monkeypatch):
        """The theme from the options decides which keys are known (theme1 reads top, medium
        doesn't)."""
        site(tmp_path, {"g/01 a.txt": "top: 10\n---\n", "_config.yml": "theme_dir: medium\n"})
        assert self.run(tmp_path, monkeypatch).exit_code == 1
        assert self.run(tmp_path, monkeypatch, "--set", "theme_dir=theme1").exit_code == 0

    def test_writes_nothing(self, tmp_path, monkeypatch):
        site(tmp_path, {})
        self.run(tmp_path, monkeypatch)
        assert not (tmp_path / "_site").exists()
