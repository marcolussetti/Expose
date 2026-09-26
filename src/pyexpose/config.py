"""Configuration management for PyExpose.

Handles loading configuration from _config.json files and applying
defaults and validation.
"""

import json
import os
from pathlib import Path
from typing import Any

# Video format -> container extension
VIDEO_FORMAT_EXTENSIONS = {"h264": "mp4", "h265": "mp4", "vp9": "webm", "vp8": "webm", "ogv": "ogv"}

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
    # PyExpose-only: parallel workers for image encoding / file reading (0 = one per CPU)
    "jobs": 0,
}


class ConfigError(ValueError):
    """Raised when the configuration is malformed or has invalid values."""


def parse_override(item: str) -> tuple[str, Any]:
    """Parse a ``KEY=VALUE`` override. VALUE is JSON if it parses, else a plain string.

    Examples: ``jpeg_quality=85``, ``resolution=[1920,640]``, ``site_title=My Trip``.
    """
    key, sep, raw = item.partition("=")
    key = key.strip()
    if not sep or not key:
        raise ConfigError(f"Invalid --set value {item!r}: expected KEY=VALUE")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    return key, value


class Config:
    """Configuration container with validation."""

    def __init__(self, config_dict: dict[str, Any]):
        """Initialize configuration from dictionary.

        Args:
            config_dict: Configuration dictionary.
        """
        self._config = config_dict

    @classmethod
    def load(
        cls,
        topdir: Path,
        scriptdir: Path,
        config_path: Path | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> Config:
        """Load configuration: defaults, then the config file, then overrides.

        Args:
            topdir: Top-level directory (where _config.json might be).
            scriptdir: Script directory (for resolving theme paths).
            config_path: Explicit config file. Must exist if given; defaults to
                ``topdir/_config.json`` (optional).
            overrides: Values that take precedence over the file (e.g. from ``--set``).

        Returns:
            Config instance.

        Raises:
            ConfigError: If the config file is missing (when explicit) or not valid JSON.
        """
        config = dict(DEFAULT_CONFIG)

        if config_path is not None:
            config_path = Path(config_path)
            if not config_path.exists():
                raise ConfigError(f"Config file not found: {config_path}")
        else:
            config_path = Path(topdir) / "_config.json"

        if config_path.exists():
            try:
                user_config = json.loads(config_path.read_text())
            except json.JSONDecodeError as e:
                raise ConfigError(f"{config_path}: invalid JSON ({e})") from e
            if not isinstance(user_config, dict):
                raise ConfigError(f"{config_path}: expected a JSON object at the top level")
            config.update(user_config)

        if overrides:
            config.update(overrides)

        return cls(config)

    def validate(self, topdir: Path | None = None) -> list[str]:
        """Check values, raising on errors.

        Args:
            topdir: Gallery root, used to check that the theme can be found.

        Returns:
            Warnings (e.g. unknown keys) that don't prevent a build.

        Raises:
            ConfigError: Describing every invalid value found.
        """
        c = self._config
        errors = []

        def is_int(v):
            return isinstance(v, int) and not isinstance(v, bool)

        def is_num(v):
            return isinstance(v, (int, float)) and not isinstance(v, bool)

        res = c.get("resolution")
        if not (isinstance(res, list) and res and all(is_int(r) and r > 0 for r in res)):
            errors.append(f"resolution must be a non-empty list of positive integers, got {res!r}")

        bitrate = c.get("bitrate")
        if not (
            isinstance(bitrate, list) and bitrate and all(is_num(b) and b > 0 for b in bitrate)
        ):
            errors.append(f"bitrate must be a non-empty list of positive numbers, got {bitrate!r}")

        formats = c.get("video_formats")
        if not isinstance(formats, list) or any(f not in VIDEO_FORMAT_EXTENSIONS for f in formats):
            known = ", ".join(VIDEO_FORMAT_EXTENSIONS)
            errors.append(f"video_formats must be a list drawn from {known}; got {formats!r}")

        quality = c.get("jpeg_quality")
        if not (is_int(quality) and 1 <= quality <= 100):
            errors.append(f"jpeg_quality must be an integer from 1 to 100, got {quality!r}")

        ratio = c.get("bitrate_maxratio")
        if not (is_num(ratio) and ratio >= 1):
            errors.append(f"bitrate_maxratio must be a number >= 1, got {ratio!r}")

        jobs = c.get("jobs", 0)
        if not (is_int(jobs) and jobs >= 0):
            errors.append(f"jobs must be an integer >= 0 (0 = one per CPU), got {jobs!r}")

        if topdir is not None:
            from pyexpose.themes import resolve_theme_dir

            try:
                resolve_theme_dir(c.get("theme_dir", ""), Path(topdir))
            except FileNotFoundError as e:
                errors.append(str(e))

        if errors:
            raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errors))

        return [f"Unknown config key ignored: {k}" for k in c if k not in DEFAULT_CONFIG]

    def worker_count(self) -> int:
        """Number of parallel workers to use (``jobs`` config, 0 = one per CPU)."""
        jobs = self._config.get("jobs") or 0
        return max(1, jobs or os.cpu_count() or 1)

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


def load_config(topdir: Path, scriptdir: Path) -> Config:
    """Load configuration from _config.json or use defaults.

    Convenience wrapper around Config.load() for backward compatibility.

    Args:
        topdir: Top-level directory (where _config.json might be).
        scriptdir: Script directory.

    Returns:
        Config instance.
    """
    return Config.load(topdir, scriptdir)
