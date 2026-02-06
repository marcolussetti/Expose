"""Tests for CLI entry points and main functions."""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from expose import check_dependencies, load_config, main, DEFAULT_CONFIG


class TestCheckDependencies:
    """Tests for check_dependencies function."""

    def test_check_dependencies_success(self):
        """Test check_dependencies when all dependencies are present."""
        with mock.patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: f"/usr/bin/{cmd}"
            # Should not raise or exit
            check_dependencies()

    def test_check_dependencies_missing_convert(self):
        """Test check_dependencies when convert is missing."""
        with mock.patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: None if cmd == "convert" else f"/usr/bin/{cmd}"
            with mock.patch("sys.exit") as mock_exit:
                check_dependencies()
                mock_exit.assert_called_once_with(1)

    def test_check_dependencies_missing_identify(self):
        """Test check_dependencies when identify is missing."""
        with mock.patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: None if cmd == "identify" else f"/usr/bin/{cmd}"
            with mock.patch("sys.exit") as mock_exit:
                check_dependencies()
                mock_exit.assert_called_once_with(1)


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

    @mock.patch("expose.check_dependencies")
    @mock.patch("expose.ExposeGenerator")
    @mock.patch("signal.signal")
    @mock.patch("atexit.register")
    def test_main_basic(self, mock_register, mock_signal, mock_generator_class, mock_check):
        """Test main() runs successfully with default args."""
        mock_generator = mock.MagicMock()
        mock_generator_class.return_value = mock_generator

        with mock.patch("sys.argv", ["expose"]):
            main()

        mock_check.assert_called_once()
        mock_generator_class.assert_called_once()
        mock_generator.run.assert_called_once()

    @mock.patch("expose.check_dependencies")
    @mock.patch("expose.ExposeGenerator")
    @mock.patch("signal.signal")
    @mock.patch("atexit.register")
    def test_main_draft_mode(self, mock_register, mock_signal, mock_generator_class, mock_check):
        """Test main() with -d (draft) flag."""
        mock_generator = mock.MagicMock()
        mock_generator_class.return_value = mock_generator

        with mock.patch("sys.argv", ["expose", "-d"]):
            main()

        mock_generator_class.assert_called_once()
        # Check that draft=True was passed
        call_kwargs = mock_generator_class.call_args[1]
        assert call_kwargs["draft"] is True

    @mock.patch("expose.check_dependencies")
    @mock.patch("expose.ExposeGenerator")
    @mock.patch("signal.signal")
    @mock.patch("atexit.register")
    def test_main_sets_up_signal_handlers(self, mock_register, mock_signal, mock_generator_class, mock_check):
        """Test main() sets up signal handlers."""
        mock_generator = mock.MagicMock()
        mock_generator_class.return_value = mock_generator

        with mock.patch("sys.argv", ["expose"]):
            main()

        # Should register signal handlers for SIGINT and SIGTERM
        assert mock_signal.call_count == 2
        mock_register.assert_called_once()
