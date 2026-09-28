"""Unit tests for dorothea.config module.

Tests the Config class that handles configuration loading and management.
"""

import pytest

from dorothea.config import (
    DEFAULT_CONFIG,
    DOROTHEA_DEFAULTS,
    EXPOSE_DEFAULTS,
    Config,
    ConfigError,
)


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
        """Test loading config when _config.yml doesn't exist."""
        config = Config.load(tmp_path, tmp_path)

        # Should use defaults
        assert config["site_title"] == DEFAULT_CONFIG["site_title"]
        assert config["theme_dir"] == DEFAULT_CONFIG["theme_dir"]

    def test_load_with_config_file(self, tmp_path):
        """Test loading config from _config.yml."""
        (tmp_path / "_config.yml").write_text("site_title: My Custom Site\njpeg_quality: 95\n")

        config = Config.load(tmp_path, tmp_path)

        # Custom values should override defaults
        assert config["site_title"] == "My Custom Site"
        assert config["jpeg_quality"] == 95

        # Other values should be defaults
        assert config["theme_dir"] == DEFAULT_CONFIG["theme_dir"]

    def test_load_with_partial_config(self, tmp_path):
        """Test loading config with partial overrides."""
        (tmp_path / "_config.yml").write_text("resolution:\n  - 1920\n  - 1024\n")

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
        """Verify EXPOSE_DEFAULTS (used with --legacy) match expose.sh's defaults."""
        # These are the critical defaults that must match
        assert EXPOSE_DEFAULTS["site_title"] == "My Awesome Photos"
        assert EXPOSE_DEFAULTS["theme_dir"] == "theme1"
        assert EXPOSE_DEFAULTS["jpeg_quality"] == 92
        assert EXPOSE_DEFAULTS["autorotate"] is True
        assert EXPOSE_DEFAULTS["video_formats"] == ["h264", "vp8"]
        assert EXPOSE_DEFAULTS["h264_encodespeed"] == "veryslow"
        assert EXPOSE_DEFAULTS["social_button"] is True
        assert EXPOSE_DEFAULTS["sort"] == "name"
        assert EXPOSE_DEFAULTS["extract_colors"] is True
        assert EXPOSE_DEFAULTS["backgroundcolor"] == "#000000"
        assert EXPOSE_DEFAULTS["textcolor"] == "#ffffff"


class TestLegacyDefaults:
    """Dorothea's defaults vs expose.sh's (--legacy), #24."""

    def test_dorothea_defaults_differ_only_where_intended(self):
        changed = {k for k in DEFAULT_CONFIG if DEFAULT_CONFIG[k] != EXPOSE_DEFAULTS[k]}
        assert changed == {
            "theme_dir",
            "sort",
            "video_formats",
            "h264_encodespeed",
            "social_button",
            "convert_to_srgb",
            "keep_metadata",
            "exif_display",
            "legacy",
        }
        assert DOROTHEA_DEFAULTS["exif_display"] == "icon"
        assert EXPOSE_DEFAULTS["exif_display"] == "off"
        assert DOROTHEA_DEFAULTS["theme_dir"] == "photoessay"
        assert EXPOSE_DEFAULTS["theme_dir"] == "theme1"
        assert DOROTHEA_DEFAULTS["convert_to_srgb"] is True
        assert DOROTHEA_DEFAULTS["keep_metadata"] == "camera"
        assert EXPOSE_DEFAULTS["convert_to_srgb"] is False
        assert EXPOSE_DEFAULTS["keep_metadata"] == "none"
        assert DEFAULT_CONFIG is DOROTHEA_DEFAULTS
        assert DOROTHEA_DEFAULTS["sort"] == "natural"
        assert DOROTHEA_DEFAULTS["video_formats"] == ["h264", "vp9"]
        assert DOROTHEA_DEFAULTS["h264_encodespeed"] == "slow"
        assert DOROTHEA_DEFAULTS["social_button"] is False

    def test_load_uses_dorothea_defaults(self, tmp_path):
        config = Config.load(tmp_path, tmp_path)
        assert config["sort"] == "natural"
        assert config["legacy"] is False

    def test_legacy_override(self, tmp_path):
        config = Config.load(tmp_path, tmp_path, overrides={"legacy": True})
        assert all(config[k] == v for k, v in EXPOSE_DEFAULTS.items())

    def test_legacy_in_config_file(self, tmp_path):
        (tmp_path / "_config.yml").write_text("legacy: true\njpeg_quality: 80\n")
        config = Config.load(tmp_path, tmp_path)
        assert config["video_formats"] == ["h264", "vp8"]
        assert config["jpeg_quality"] == 80  # explicit settings still win

    def test_no_legacy_overrides_config_file(self, tmp_path):
        (tmp_path / "_config.yml").write_text("legacy: true\n")
        config = Config.load(tmp_path, tmp_path, overrides={"legacy": False})
        assert config["video_formats"] == ["h264", "vp9"]

    def test_explicit_settings_win_over_either_set(self, tmp_path):
        (tmp_path / "_config.yml").write_text("sort: capture\n")
        assert Config.load(tmp_path, tmp_path)["sort"] == "capture"
        legacy = Config.load(tmp_path, tmp_path, overrides={"legacy": True})
        assert legacy["sort"] == "capture"

    def test_legacy_must_be_boolean(self, tmp_path):
        with pytest.raises(ConfigError, match="legacy must be true or false"):
            Config({**DEFAULT_CONFIG, "legacy": "yes"}).validate(tmp_path)

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

    def test_load_with_invalid_yaml(self, tmp_path):
        """A syntax error names the file and line (not silently fail)."""
        (tmp_path / "_config.yml").write_text("site_title: Trip\nresolution: [1920, 640\n")
        with pytest.raises(ConfigError, match=r"_config.yml line 3: expected ',' or ']'"):
            Config.load(tmp_path, tmp_path)

    def test_not_key_value_pairs(self, tmp_path):
        (tmp_path / "_config.yml").write_text("- a list\n- of things\n")
        with pytest.raises(ConfigError, match="expected `key: value` lines"):
            Config.load(tmp_path, tmp_path)

    def test_config_preserves_types(self, tmp_path):
        """Test that config preserves data types."""
        (tmp_path / "_config.yml").write_text(
            "jpeg_quality: 95\nautorotate: true\nresolution: [1920, 1024]\nsite_title: Test\n"
        )

        config = Config.load(tmp_path, tmp_path)

        assert isinstance(config["jpeg_quality"], int)
        assert isinstance(config["autorotate"], bool)
        assert isinstance(config["resolution"], list)
        assert isinstance(config["site_title"], str)


def test_every_setting_is_documented():
    """The configuration page must mention every key in DEFAULT_CONFIG (keeps the docs from
    drifting)."""
    from pathlib import Path

    page = Path(__file__).resolve().parents[2] / "docs" / "configuration.md"
    docs = page.read_text(encoding="utf-8")
    missing = [key for key in DEFAULT_CONFIG if f"`{key}`" not in docs]
    assert missing == []


class TestFfmpegSetting:
    def test_default_is_auto(self):
        assert DEFAULT_CONFIG["ffmpeg"] == "auto"

    @pytest.mark.parametrize("value", ["auto", "bundled"])
    def test_valid_choices(self, value, tmp_path):
        Config({**DEFAULT_CONFIG, "ffmpeg": value}).validate(tmp_path)

    def test_missing_system_ffmpeg_only_warns(self, tmp_path):
        from unittest import mock

        with mock.patch("dorothea.media.ffmpeg.shutil.which", return_value=None):
            warnings = Config({**DEFAULT_CONFIG, "ffmpeg": "system"}).validate(tmp_path)
        assert any("videos will be skipped" in w for w in warnings)

    @pytest.mark.parametrize("value", ["/no/such/ffmpeg", "", 5])
    def test_invalid_values(self, value, tmp_path):
        with pytest.raises(ConfigError, match="ffmpeg"):
            Config({**DEFAULT_CONFIG, "ffmpeg": value}).validate(tmp_path)
