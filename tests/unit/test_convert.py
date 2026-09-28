"""--convert-config for galleries (#46): metadata.txt → gallery.yml with the same settings."""

import pytest
from click.testing import CliRunner

from dorothea.captions import gallery_metadata, metadata_values
from dorothea.cli import main
from dorothea.convert import metadata_to_yaml
from dorothea.yamlfile import load_mapping


def reads_the_same(text: str) -> bool:
    """The gallery.yml gives exactly the settings the metadata.txt did."""
    from dorothea.captions import as_text

    values = {k: as_text(v) for k, v in load_mapping(metadata_to_yaml(text))[0].items()}
    return {k: v for k, v in values.items() if v} == metadata_values(text)


class TestMetadataToYaml:
    def test_plain_values_stay_as_written(self):
        text = "width: 19\nclass: textafter\nsort: capture\ndate: 2022-07-14\nfeed: no\n"
        assert metadata_to_yaml(text) == text
        assert reads_the_same(text)

    @pytest.mark.parametrize(
        "line,yaml",
        [
            ('polygon:[{"x":5, "y":0},{"x":100, "y":100}]',
             """polygon: '[{"x":5, "y":0},{"x":100, "y":100}]'"""),
            ("textcolor: #ff9518", "textcolor: '#ff9518'"),
            ("description: Iceland: the ring road", "description: 'Iceland: the ring road'"),
            ("title: 'quoted'", "title: '''quoted'''"),
            ("top: 012", "top: '012'"),
            ("image-options: -modulate 100,120", "image-options: -modulate 100,120"),
            ("video-filters: lutyuv=\"u=128:v=128\"", "video-filters: lutyuv=\"u=128:v=128\""),
        ],
    )  # fmt: skip
    def test_values_yaml_would_read_differently_are_quoted(self, line, yaml):
        assert metadata_to_yaml(line + "\n") == yaml + "\n"
        assert reads_the_same(line + "\n")

    def test_comments_blank_lines_and_stray_text(self):
        text = "# my notes\n\nwidth: 19\nnot a setting\nwidth: 30\nempty:\n"
        assert metadata_to_yaml(text) == (
            "# my notes\n\nwidth: 19\n# not a setting\n# width: 30\n# empty:\n"
        )
        assert reads_the_same(text)

    def test_windows_line_endings(self):
        assert metadata_to_yaml("width: 19\r\nsort: name\r\n") == "width: 19\nsort: name\n"


def convert(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(main, ["--convert-config"], prog_name="dorothea")


class TestConvertGalleries:
    def test_converts_and_deletes(self, tmp_path, monkeypatch):
        g = tmp_path / "01 Iceland"
        g.mkdir()
        (g / "metadata.txt").write_text("width: 19\ntextcolor: #ff9518\n")
        before = gallery_metadata(g)
        result = convert(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        assert "Wrote 01 Iceland/gallery.yml (from metadata.txt, now deleted)" in result.output
        assert not (g / "metadata.txt").exists()
        assert (g / "gallery.yml").read_text() == "width: 19\ntextcolor: '#ff9518'\n"
        assert gallery_metadata(g) == before

    def test_nested_and_hidden_folders(self, tmp_path, monkeypatch):
        for folder in ("trips/norway", "trips", "_drafts", ".git"):
            (tmp_path / folder).mkdir(parents=True, exist_ok=True)
            (tmp_path / folder / "metadata.txt").write_text("sort: name\n")
        convert(tmp_path, monkeypatch)
        assert (tmp_path / "trips/norway/gallery.yml").exists()
        assert (tmp_path / "trips/gallery.yml").exists()
        assert (tmp_path / "_drafts/metadata.txt").exists()  # ignored folders are left alone
        assert (tmp_path / ".git/metadata.txt").exists()

    def test_a_folder_with_a_gallery_yml_is_left_alone(self, tmp_path, monkeypatch):
        (tmp_path / "g").mkdir()
        (tmp_path / "g/metadata.txt").write_text("sort: name\n")
        (tmp_path / "g/gallery.yml").write_text("sort: capture\n")
        result = convert(tmp_path, monkeypatch)
        assert result.exit_code == 0
        assert (
            "g/metadata.txt: left as it is; the folder already has a gallery.yml" in result.stderr
        )
        assert (tmp_path / "g/metadata.txt").exists()
        assert (tmp_path / "g/gallery.yml").read_text() == "sort: capture\n"

    def test_config_and_galleries_together(self, tmp_path, monkeypatch):
        (tmp_path / "_config.sh").write_text('site_title="Trip"\n')
        (tmp_path / "g").mkdir()
        (tmp_path / "g/metadata.txt").write_text("sort: name\n")
        result = convert(tmp_path, monkeypatch)
        assert "Wrote _config.yml (from _config.sh, now deleted)" in result.output
        assert "Wrote g/gallery.yml (from metadata.txt, now deleted)" in result.output
        assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == [
            "_config.yml",
            "gallery.yml",
        ]

    def test_running_twice_does_nothing_more(self, tmp_path, monkeypatch):
        (tmp_path / "g").mkdir()
        (tmp_path / "g/metadata.txt").write_text("sort: name\n")
        convert(tmp_path, monkeypatch)
        result = convert(tmp_path, monkeypatch)
        assert result.exit_code == 0
        assert "Nothing to convert" in result.output
