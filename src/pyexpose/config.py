"""Configuration management for PyExpose.

Handles loading configuration from _config.json files and applying
defaults and validation.
"""

import json
from pathlib import Path
from typing import Any

# Default configuration matching expose.sh
DEFAULT_CONFIG = {
    "site_title": "My Awesome Photos",
    "theme_dir": "theme1",
    "resolution": [3840, 2560, 1920, 1280, 1024, 640],
    "jpeg_quality": 92,
    "autorotate": True,
    "video_formats": ["h264", "vp8"],
    "bitrate": [40, 24, 12, 7, 4, 2],
    "bitrate_maxratio": 2,
    "disable_audio": True,
    "extract_colors": True,
    "backgroundcolor": "#000000",
    "textcolor": "#ffffff",
    "default_palette": [
        "#000000",
        "#222222",
        "#444444",
        "#666666",
        "#999999",
        "#cccccc",
        "#ffffff",
    ],
    "override_textcolor": True,
    "text_toggle": True,
    "social_button": True,
    "download_button": False,
    "download_readme": "All rights reserved",
    "disqus_shortname": "",
    "sequence_keyword": "imagesequence",
    "sequence_framerate": 24,
    "h264_encodespeed": "veryslow",
    "vp9_encodespeed": 1,
    "ffmpeg_threads": 0,
}


class Config:
    """Configuration container with validation."""

    def __init__(self, config_dict: dict[str, Any]):
        """Initialize configuration from dictionary.

        Args:
            config_dict: Configuration dictionary.
        """
        self._config = config_dict

    @classmethod
    def load(cls, topdir: Path, scriptdir: Path) -> "Config":
        """Load configuration from _config.json or use defaults.

        Args:
            topdir: Top-level directory (where _config.json might be).
            scriptdir: Script directory (for resolving theme paths).

        Returns:
            Config instance.
        """
        config = dict(DEFAULT_CONFIG)

        config_path = topdir / "_config.json"
        if config_path.exists():
            with open(config_path) as f:
                user_config = json.load(f)
                config.update(user_config)

        return cls(config)

    def apply_draft_mode(self) -> None:
        """Apply draft mode settings (fast preview)."""
        print("Draft mode On")
        self._config["resolution"] = [1024]
        self._config["bitrate"] = [4]
        self._config["video_formats"] = ["h264"]
        self._config["download_button"] = False

    def get(self, key: str, default=None):
        """Get configuration value.

        Args:
            key: Configuration key.
            default: Default value if key not found.

        Returns:
            Configuration value or default.
        """
        return self._config.get(key, default)

    def __getitem__(self, key: str):
        """Get configuration value using dict syntax.

        Args:
            key: Configuration key.

        Returns:
            Configuration value.

        Raises:
            KeyError: If key not found.
        """
        return self._config[key]

    def __setitem__(self, key: str, value: Any):
        """Set configuration value using dict syntax.

        Args:
            key: Configuration key.
            value: Configuration value.
        """
        self._config[key] = value


def load_config(topdir: Path, scriptdir: Path) -> "Config":
    """Load configuration from _config.json or use defaults.

    Convenience wrapper around Config.load() for backward compatibility.

    Args:
        topdir: Top-level directory (where _config.json might be).
        scriptdir: Script directory.

    Returns:
        Config instance.
    """
    return Config.load(topdir, scriptdir)
