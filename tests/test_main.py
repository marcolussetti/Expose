"""Tests for CLI entry points and main functions."""

import json
import signal
from unittest import mock

import pytest
from click.testing import CliRunner

from dorothea import __version__
from dorothea.cli import main
from dorothea.config import DEFAULT_CONFIG, load_config


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_defaults(self, tmp_path):
        """Test load_config returns defaults when no config file exists."""
        config = load_config(tmp_path, tmp_path)
        assert config["site_title"] == DEFAULT_CONFIG["site_title"]
        assert config["theme_dir"] == DEFAULT_CONFIG["theme_dir"]

    def test_load_config_from_file(self, tmp_path):
        """Test load_config loads from _config.json."""
        config_file = tmp_path / "_config.json"
        custom_config = {
            "site_title": "Custom Title",
            "theme_dir": "custom_theme",
            "jpeg_quality": 85,
        }
        config_file.write_text(json.dumps(custom_config))

        config = load_config(tmp_path, tmp_path)
        assert config["site_title"] == "Custom Title"
        assert config["theme_dir"] == "custom_theme"
        assert config["jpeg_quality"] == 85
        # Other defaults should still be present
        assert config["autorotate"] == DEFAULT_CONFIG["autorotate"]

    def test_load_config_partial_override(self, tmp_path):
        """Test load_config merges partial config with defaults."""
        config_file = tmp_path / "_config.json"
        config_file.write_text(json.dumps({"site_title": "Only Title"}))

        config = load_config(tmp_path, tmp_path)
        assert config["site_title"] == "Only Title"
        assert config["theme_dir"] == DEFAULT_CONFIG["theme_dir"]


def invoke(argv, monkeypatch, cwd, prog="dorothea"):
    """Run the CLI in ``cwd`` with the generator mocked. Returns (result, generator class mock)."""
    monkeypatch.chdir(cwd)
    with (
        mock.patch("dorothea.cli.ExposeGenerator") as gen_class,
        mock.patch("signal.signal") as signal_mock,
        mock.patch("atexit.register") as atexit_mock,
    ):
        result = CliRunner().invoke(main, argv, prog_name=prog)
    gen_class.signal_mock, gen_class.atexit_mock = signal_mock, atexit_mock
    return result, gen_class


def passed_config(gen_class):
    """The Config object main() handed to ExposeGenerator."""
    return gen_class.call_args[0][2]


class TestMain:
    """Tests for the main() CLI entry point."""

    def test_main_basic(self, tmp_path, monkeypatch):
        result, gen_class = invoke([], monkeypatch, tmp_path)
        assert result.exit_code == 0, result.output
        gen_class.assert_called_once()
        gen_class.return_value.run.assert_called_once()

    def test_main_draft_mode(self, tmp_path, monkeypatch):
        result, gen_class = invoke(["-d"], monkeypatch, tmp_path)
        assert result.exit_code == 0, result.output
        assert gen_class.call_args[1]["draft"] is True

    def test_main_sets_up_signal_handlers(self, tmp_path, monkeypatch):
        result, gen_class = invoke([], monkeypatch, tmp_path)
        assert result.exit_code == 0, result.output
        # SIGINT and SIGTERM handlers during the build (restored after it, for `serve`), plus an
        # atexit cleanup
        installed = [c.args[0] for c in gen_class.signal_mock.call_args_list[:2]]
        assert installed == [signal.SIGINT, signal.SIGTERM]
        assert gen_class.signal_mock.call_count == 4
        gen_class.atexit_mock.assert_called_once()

    def test_help(self, tmp_path, monkeypatch):
        result, _ = invoke(["--help"], monkeypatch, tmp_path)
        assert result.exit_code == 0
        for flag in ("--draft", "--dry-run", "--config", "--set", "--jobs", "--ffmpeg"):
            assert flag in result.output


class TestCliOptions:
    """Tests for --config, --set, --jobs, --ffmpeg, --version and validation errors."""

    @pytest.mark.parametrize("prog", ["dorothea", "expose"])
    def test_version_uses_invoked_name(self, prog, tmp_path, monkeypatch):
        result, _ = invoke(["--version"], monkeypatch, tmp_path, prog=prog)
        assert result.exit_code == 0
        assert result.output.strip() == f"{prog} {__version__}"

    def test_set_overrides_file_and_parses_json(self, tmp_path, monkeypatch):
        (tmp_path / "_config.json").write_text(json.dumps({"jpeg_quality": 70}))
        result, gen_class = invoke(
            ["--set", "jpeg_quality=85", "--set", "resolution=[1920, 640]",
             "--set", "site_title=My Trip"],
            monkeypatch,
            tmp_path,
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        config = passed_config(gen_class)
        assert config["jpeg_quality"] == 85
        assert config["resolution"] == [1920, 640]
        assert config["site_title"] == "My Trip"

    def test_config_path(self, tmp_path, monkeypatch):
        other = tmp_path / "elsewhere.json"
        other.write_text(json.dumps({"site_title": "From Elsewhere"}))
        _, gen_class = invoke(["--config", str(other)], monkeypatch, tmp_path)
        assert passed_config(gen_class)["site_title"] == "From Elsewhere"

    def test_jobs_flag(self, tmp_path, monkeypatch):
        _, gen_class = invoke(["-j", "3"], monkeypatch, tmp_path)
        assert passed_config(gen_class).worker_count() == 3

    def test_draft_overrides_set(self, tmp_path, monkeypatch):
        """Draft mode wins over --set for the values it controls."""
        _, gen_class = invoke(["-d", "--set", "resolution=[3840]"], monkeypatch, tmp_path)
        assert passed_config(gen_class)["resolution"] == [1024]

    @pytest.mark.parametrize("choice", ["auto", "bundled", "system"])
    def test_ffmpeg_flag(self, choice, tmp_path, monkeypatch):
        result, gen_class = invoke(["--ffmpeg", choice], monkeypatch, tmp_path)
        assert result.exit_code == 0, result.output
        assert passed_config(gen_class)["ffmpeg"] == choice

    def test_ffmpeg_flag_overrides_config_file(self, tmp_path, monkeypatch):
        (tmp_path / "_config.json").write_text(json.dumps({"ffmpeg": "system"}))
        _, gen_class = invoke(["--ffmpeg", "bundled"], monkeypatch, tmp_path)
        assert passed_config(gen_class)["ffmpeg"] == "bundled"

    @pytest.mark.parametrize(
        "argv,message",
        [
            (["--set", "jpeg_quality=500"], "jpeg_quality"),
            (["--set", 'video_formats=["av1"]'], "video_formats"),
            (["--set", "theme_dir=nope"], "Theme 'nope' not found"),
            (["--set", "novalue"], "KEY=VALUE"),
            (["--config", "missing.json"], "Config file not found"),
            (["--ffmpeg", "/no/such/ffmpeg"], "is not an executable file"),
        ],
    )
    def test_invalid_config_exits_2(self, argv, message, tmp_path, monkeypatch):
        result, gen_class = invoke(argv, monkeypatch, tmp_path)
        assert result.exit_code == 2
        assert message in result.stderr
        assert result.stderr.startswith("dorothea: ")
        gen_class.assert_not_called()

    def test_unknown_key_warns(self, tmp_path, monkeypatch):
        result, _ = invoke(["--set", "site_titel=typo"], monkeypatch, tmp_path)
        assert "Unknown config key ignored: site_titel" in result.stderr
