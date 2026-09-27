"""Tests for reading expose.sh ``_config.sh`` files and ``--convert-config``."""

import json
from unittest import mock

import pytest

from pyexpose.cli import main
from pyexpose.config import Config, parse_config_sh


class TestParseConfigSh:
    def test_scalars_quotes_and_comments(self):
        values, warnings = parse_config_sh(
            "# a comment\n"
            'site_title="My Photos"   # trailing comment\n'
            "theme_dir=theme2\n"
            "download_readme='All rights $reserved'\n"
            "#social_button=false\n"
        )
        assert values == {
            "site_title": "My Photos",
            "theme_dir": "theme2",
            "download_readme": "All rights $reserved",  # single quotes: no expansion
        }
        assert warnings == []

    def test_types_follow_defaults(self):
        values, _ = parse_config_sh(
            "jpeg_quality=85\nautorotate=false\nbitrate_maxratio=1.5\nsite_title=2022\n"
        )
        assert values == {
            "jpeg_quality": 85,
            "autorotate": False,
            "bitrate_maxratio": 1.5,
            "site_title": "2022",  # string setting stays a string
        }

    def test_arrays(self):
        values, _ = parse_config_sh(
            'resolution=(1920 1280 640)\ndefault_palette=("#000000" "#ffffff")\nvideo_formats=()\n'
        )
        assert values == {
            "resolution": [1920, 1280, 640],
            "default_palette": ["#000000", "#ffffff"],
            "video_formats": [],
        }

    @pytest.mark.parametrize(
        "line,message",
        [
            ("bad=$(rm -rf /)", "shell expansion"),
            ("bad=`whoami`", "shell expansion"),
            ('bad="${HOME}/x"', "shell expansion"),
            ("export site_title=x", "not a simple assignment"),
            ("if [ -f x ]; then", "not a simple assignment"),
            ("x=a b", "unquoted value with spaces"),
            ("resolution=(1920", "array must open and close"),
        ],
    )
    def test_unsafe_or_unsupported_lines_are_skipped(self, line, message):
        values, warnings = parse_config_sh(f"site_title=ok\n{line}\n")
        assert values == {"site_title": "ok"}
        assert len(warnings) == 1
        assert message in warnings[0]
        assert "line 2" in warnings[0]


class TestLoadConfigSh:
    def test_config_sh_used_when_no_json(self, tmp_path):
        (tmp_path / "_config.sh").write_text('site_title="From Shell"\n')
        config = Config.load(tmp_path, tmp_path)
        assert config["site_title"] == "From Shell"
        assert any("--convert-config" in w for w in config.load_warnings)

    def test_json_wins_over_sh(self, tmp_path):
        (tmp_path / "_config.sh").write_text('site_title="From Shell"\n')
        (tmp_path / "_config.json").write_text(json.dumps({"site_title": "From JSON"}))
        config = Config.load(tmp_path, tmp_path)
        assert config["site_title"] == "From JSON"
        assert config.load_warnings == []

    def test_explicit_sh_path(self, tmp_path):
        other = tmp_path / "other.sh"
        other.write_text("jpeg_quality=70\n")
        config = Config.load(tmp_path, tmp_path, config_path=other)
        assert config["jpeg_quality"] == 70


class TestConvertConfig:
    def run(self, tmp_path, monkeypatch, *argv):
        monkeypatch.chdir(tmp_path)
        with (
            mock.patch("sys.argv", ["expose", "--convert-config", *argv]),
            pytest.raises(SystemExit) as e,
        ):
            main()
        return e.value.code

    def test_writes_json(self, tmp_path, monkeypatch):
        (tmp_path / "_config.sh").write_text('site_title="Trip"\nresolution=(1280 640)\nbad=$(x)\n')
        assert self.run(tmp_path, monkeypatch) == 0
        data = json.loads((tmp_path / "_config.json").read_text())
        assert data == {"site_title": "Trip", "resolution": [1280, 640]}

    def test_refuses_to_overwrite(self, tmp_path, monkeypatch):
        (tmp_path / "_config.sh").write_text('site_title="Trip"\n')
        (tmp_path / "_config.json").write_text("{}")
        assert self.run(tmp_path, monkeypatch) == 2
        assert (tmp_path / "_config.json").read_text() == "{}"

    def test_missing_source(self, tmp_path, monkeypatch):
        assert self.run(tmp_path, monkeypatch) == 2
