"""Unit tests for pyexpose.config module.

Tests the Config class that handles configuration loading and management.
"""

import json

import pytest
from pyexpose.config import DEFAULT_CONFIG, Config


class TestConfigDefaults:
    """Test default configuration values."""

    def test_default_config_exists(self):
        """Test that DEFAULT_CONFIG dictionary exists."""
        assert DEFAULT_CONFIG is not None
        assert isinstance(DEFAULT_CONFIG, dict)

    def test_default_config_has_required_keys(self):
        """Test that DEFAULT_CONFIG has all required keys."""
        required_keys = [
            "site_title",
            "theme_dir",
            "resolution",
            "jpeg_quality",
            "autorotate",
            "video_formats",
            "bitrate",
            "extract_colors",
            "backgroundcolor",
            "textcolor",
        ]

        for key in required_keys:
            assert key in DEFAULT_CONFIG

    def test_default_resolution_list(self):
        """Test that default resolution is a list."""
        assert isinstance(DEFAULT_CONFIG["resolution"], list)
        assert len(DEFAULT_CONFIG["resolution"]) > 0

    def test_default_video_formats(self):
        """Test that default video formats is a list."""
        assert isinstance(DEFAULT_CONFIG["video_formats"], list)
        assert "h264" in DEFAULT_CONFIG["video_formats"]


class TestConfigLoad:
    """Test Config.load() method."""

    def test_load_without_config_file(self, tmp_path):
        """Test loading config when _config.json doesn't exist."""
        config = Config.load(tmp_path, tmp_path)

        # Should use defaults
        assert config["site_title"] == DEFAULT_CONFIG["site_title"]
        assert config["theme_dir"] == DEFAULT_CONFIG["theme_dir"]

    def test_load_with_config_file(self, tmp_path):
        """Test loading config from _config.json."""
        # Create a config file
        config_data = {
            "site_title": "My Custom Site",
            "jpeg_quality": 95,
        }

        config_path = tmp_path / "_config.json"
        with open(config_path, "w") as f:
            json.dump(config_data, f)

        config = Config.load(tmp_path, tmp_path)

        # Custom values should override defaults
        assert config["site_title"] == "My Custom Site"
        assert config["jpeg_quality"] == 95

        # Other values should be defaults
        assert config["theme_dir"] == DEFAULT_CONFIG["theme_dir"]

    def test_load_with_partial_config(self, tmp_path):
        """Test loading config with partial overrides."""
        config_data = {
            "resolution": [1920, 1024],
        }

        config_path = tmp_path / "_config.json"
        with open(config_path, "w") as f:
            json.dump(config_data, f)

        config = Config.load(tmp_path, tmp_path)

        # Custom resolution
        assert config["resolution"] == [1920, 1024]

        # Other values still defaults
        assert config["site_title"] == DEFAULT_CONFIG["site_title"]


class TestConfigApplyDraftMode:
    """Test Config.apply_draft_mode() method."""

    def test_apply_draft_mode_changes_resolution(self, tmp_path):
        """Test that draft mode sets resolution to [1024]."""
        config = Config.load(tmp_path, tmp_path)
        config.apply_draft_mode()

        assert config["resolution"] == [1024]

    def test_apply_draft_mode_changes_bitrate(self, tmp_path):
        """Test that draft mode sets bitrate to [4]."""
        config = Config.load(tmp_path, tmp_path)
        config.apply_draft_mode()

        assert config["bitrate"] == [4]

    def test_apply_draft_mode_changes_video_formats(self, tmp_path):
        """Test that draft mode sets video_formats to ['h264']."""
        config = Config.load(tmp_path, tmp_path)
        config.apply_draft_mode()

        assert config["video_formats"] == ["h264"]

    def test_apply_draft_mode_disables_download_button(self, tmp_path):
        """Test that draft mode disables download button."""
        config = Config.load(tmp_path, tmp_path)
        config.apply_draft_mode()

        assert config["download_button"] is False


class TestConfigAccessors:
    """Test Config accessor methods."""

    def test_getitem(self, tmp_path):
        """Test dictionary-style access."""
        config = Config.load(tmp_path, tmp_path)
        assert config["site_title"] == DEFAULT_CONFIG["site_title"]

    def test_get_with_default(self, tmp_path):
        """Test get() with default value."""
        config = Config.load(tmp_path, tmp_path)

        # Existing key
        assert config.get("site_title") == DEFAULT_CONFIG["site_title"]

        # Non-existent key with default
        assert config.get("nonexistent", "default") == "default"

    def test_setitem(self, tmp_path):
        """Test setting values."""
        config = Config.load(tmp_path, tmp_path)
        config["site_title"] = "New Title"

        assert config["site_title"] == "New Title"

    def test_getitem_missing_key(self, tmp_path):
        """Test accessing missing key raises KeyError."""
        config = Config.load(tmp_path, tmp_path)

        with pytest.raises(KeyError):
            _ = config["nonexistent_key"]


class TestConfigParity:
    """Test that config matches expose.py behavior."""

    def test_config_matches_default_config_dict(self):
        """Verify DEFAULT_CONFIG matches expose.py defaults."""
        # These are the critical defaults that must match
        assert DEFAULT_CONFIG["site_title"] == "My Awesome Photos"
        assert DEFAULT_CONFIG["theme_dir"] == "theme1"
        assert DEFAULT_CONFIG["jpeg_quality"] == 92
        assert DEFAULT_CONFIG["autorotate"] is True
        assert DEFAULT_CONFIG["video_formats"] == ["h264", "vp8"]
        assert DEFAULT_CONFIG["extract_colors"] is True
        assert DEFAULT_CONFIG["backgroundcolor"] == "#000000"
        assert DEFAULT_CONFIG["textcolor"] == "#ffffff"

    def test_draft_mode_matches_expose_sh(self, tmp_path):
        """Verify draft mode matches expose.sh behavior."""
        config = Config.load(tmp_path, tmp_path)
        config.apply_draft_mode()

        # These match the draft mode settings in expose.sh
        assert config["resolution"] == [1024]
        assert config["bitrate"] == [4]
        assert config["video_formats"] == ["h264"]
        assert config["download_button"] is False


class TestConfigEdgeCases:
    """Test edge cases and error handling."""

    def test_load_with_invalid_json(self, tmp_path):
        """Test loading config with invalid JSON."""
        config_path = tmp_path / "_config.json"
        config_path.write_text("{ invalid json }")

        # Should raise an error (not silently fail)
        with pytest.raises(json.JSONDecodeError):
            Config.load(tmp_path, tmp_path)

    def test_config_preserves_types(self, tmp_path):
        """Test that config preserves data types."""
        config_data = {
            "jpeg_quality": 95,  # int
            "autorotate": True,  # bool
            "resolution": [1920, 1024],  # list
            "site_title": "Test",  # str
        }

        config_path = tmp_path / "_config.json"
        with open(config_path, "w") as f:
            json.dump(config_data, f)

        config = Config.load(tmp_path, tmp_path)

        assert isinstance(config["jpeg_quality"], int)
        assert isinstance(config["autorotate"], bool)
        assert isinstance(config["resolution"], list)
        assert isinstance(config["site_title"], str)
