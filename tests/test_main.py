"""Tests for CLI entry points and main functions."""

import json
from unittest import mock

import pytest

from pyexpose import __version__
from pyexpose.cli import main
from pyexpose.config import DEFAULT_CONFIG, load_config


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


class TestMain:
    """Tests for main() CLI entry point."""

    @mock.patch("pyexpose.cli.ExposeGenerator")
    @mock.patch("signal.signal")
    @mock.patch("atexit.register")
    def test_main_basic(self, mock_register, mock_signal, mock_generator_class):
        """Test main() runs successfully with default args."""
        mock_generator = mock.MagicMock()
        mock_generator_class.return_value = mock_generator

        with mock.patch("sys.argv", ["expose"]):
            main()

        mock_generator_class.assert_called_once()
        mock_generator.run.assert_called_once()

    @mock.patch("pyexpose.cli.ExposeGenerator")
    @mock.patch("signal.signal")
    @mock.patch("atexit.register")
    def test_main_draft_mode(self, mock_register, mock_signal, mock_generator_class):
        """Test main() with -d (draft) flag."""
        mock_generator = mock.MagicMock()
        mock_generator_class.return_value = mock_generator

        with mock.patch("sys.argv", ["expose", "-d"]):
            main()

        mock_generator_class.assert_called_once()
        # Check that draft=True was passed
        call_kwargs = mock_generator_class.call_args[1]
        assert call_kwargs["draft"] is True

    @mock.patch("pyexpose.cli.ExposeGenerator")
    @mock.patch("signal.signal")
    @mock.patch("atexit.register")
    def test_main_sets_up_signal_handlers(self, mock_register, mock_signal, mock_generator_class):
        """Test main() sets up signal handlers."""
        mock_generator = mock.MagicMock()
        mock_generator_class.return_value = mock_generator

        with mock.patch("sys.argv", ["expose"]):
            main()

        # Should register signal handlers for SIGINT and SIGTERM
        assert mock_signal.call_count == 2
        mock_register.assert_called_once()


def run_main(argv, monkeypatch, cwd):
    """Run main() in ``cwd`` with the generator mocked; return the generator class mock."""
    monkeypatch.chdir(cwd)
    with (
        mock.patch("pyexpose.cli.ExposeGenerator") as gen_class,
        mock.patch("signal.signal"),
        mock.patch("atexit.register"),
        mock.patch("sys.argv", ["expose", *argv]),
    ):
        main()
    return gen_class


def passed_config(gen_class):
    """The Config object main() handed to ExposeGenerator."""
    return gen_class.call_args[0][2]


class TestCliOptions:
    """Tests for --config, --set, --jobs, --version and validation errors."""

    def test_version(self, capsys):
        with mock.patch("sys.argv", ["expose", "--version"]), pytest.raises(SystemExit) as e:
            main()
        assert e.value.code == 0
        assert __version__ in capsys.readouterr().out

    def test_set_overrides_file_and_parses_json(self, tmp_path, monkeypatch):
        (tmp_path / "_config.json").write_text(json.dumps({"jpeg_quality": 70}))
        gen_class = run_main(
            ["--set", "jpeg_quality=85", "--set", "resolution=[1920, 640]",
             "--set", "site_title=My Trip"],
            monkeypatch,
            tmp_path,
        )  # fmt: skip
        config = passed_config(gen_class)
        assert config["jpeg_quality"] == 85
        assert config["resolution"] == [1920, 640]
        assert config["site_title"] == "My Trip"

    def test_config_path(self, tmp_path, monkeypatch):
        other = tmp_path / "elsewhere.json"
        other.write_text(json.dumps({"site_title": "From Elsewhere"}))
        gen_class = run_main(["--config", str(other)], monkeypatch, tmp_path)
        assert passed_config(gen_class)["site_title"] == "From Elsewhere"

    def test_jobs_flag(self, tmp_path, monkeypatch):
        gen_class = run_main(["-j", "3"], monkeypatch, tmp_path)
        assert passed_config(gen_class).worker_count() == 3

    def test_draft_overrides_set(self, tmp_path, monkeypatch):
        """Draft mode wins over --set for the values it controls."""
        gen_class = run_main(["-d", "--set", "resolution=[3840]"], monkeypatch, tmp_path)
        assert passed_config(gen_class)["resolution"] == [1024]

    @pytest.mark.parametrize(
        "argv,message",
        [
            (["--set", "jpeg_quality=500"], "jpeg_quality"),
            (["--set", 'video_formats=["av1"]'], "video_formats"),
            (["--set", "theme_dir=nope"], "Theme 'nope' not found"),
            (["--set", "novalue"], "KEY=VALUE"),
            (["--config", "missing.json"], "Config file not found"),
        ],
    )
    def test_invalid_config_exits_2(self, argv, message, tmp_path, monkeypatch, capsys):
        with pytest.raises(SystemExit) as e:
            run_main(argv, monkeypatch, tmp_path)
        assert e.value.code == 2
        assert message in capsys.readouterr().err

    def test_unknown_key_warns(self, tmp_path, monkeypatch, capsys):
        run_main(["--set", "site_titel=typo"], monkeypatch, tmp_path)
        assert "Unknown config key ignored: site_titel" in capsys.readouterr().err
