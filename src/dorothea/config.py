"""Configuration management for Dorothea.

Handles loading configuration from _config.json files and applying
defaults and validation.
"""

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, TypeIs

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
    # Dorothea-only: which ffmpeg to use: "auto" (system, else bundled), "bundled", "system",
    # or a path to an ffmpeg binary
    "ffmpeg": "auto",
    # Dorothea-only: parallel workers for image encoding / file reading (0 = one per CPU)
    "jobs": 0,
}


def is_int(value: object) -> TypeIs[int]:
    """True for ints but not bools (``True`` is an int in Python)."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value: object) -> TypeIs[int | float]:
    """True for ints and floats but not bools."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class ConfigError(ValueError):
    """Raised when the configuration is malformed or has invalid values."""


def find_config_file(topdir: Path) -> Path | None:
    """Return ``_config.json`` if present, else expose.sh's ``_config.sh``, else None."""
    for name in ("_config.json", "_config.sh"):
        candidate = topdir / name
        if candidate.exists():
            return candidate
    return None


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


_SH_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _has_expansion(raw: str) -> bool:
    """True if ``raw`` contains ``$`` or a backtick outside single quotes (i.e. shell code)."""
    in_single = in_double = False
    for ch in raw:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch in "$`" and not in_single:
            return True
        elif ch == "#" and not in_single and not in_double:
            break  # rest is a comment
    return False


def _coerce(key: str, value: str, element: bool = False) -> Any:
    """Convert a shell string to the type DEFAULT_CONFIG uses for ``key``."""
    default = DEFAULT_CONFIG.get(key)
    if element and isinstance(default, list):
        default = default[0] if default else None
    if isinstance(default, bool) or (default is None and value in ("true", "false")):
        if value in ("true", "false"):
            return value == "true"
        return value
    if isinstance(default, (int, float)) or default is None:
        for convert in (int, float):
            try:
                return convert(value)
            except ValueError:
                pass
    return value


def parse_config_sh(text: str) -> tuple[dict[str, Any], list[str]]:
    """Parse the simple assignments expose.sh users put in ``_config.sh``.

    This never executes shell. Supported: ``key=value``, ``key="value"``, ``key='value'``,
    ``key=(a b "c d")`` and ``#`` comments. Values are converted to the type of the matching
    ``DEFAULT_CONFIG`` entry (``true``/``false`` → bool, numbers → int/float).

    Returns:
        (values, warnings) — lines that can't be parsed safely are skipped with a warning.
    """
    values: dict[str, Any] = {}
    warnings: list[str] = []

    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        match = _SH_ASSIGNMENT.match(stripped)
        if not match:
            warnings.append(f"_config.sh line {lineno}: not a simple assignment, ignored")
            continue
        key, raw = match.groups()

        if _has_expansion(raw):
            warnings.append(f"_config.sh line {lineno}: shell expansion in {key}, ignored")
            continue

        try:
            if raw.lstrip().startswith("("):
                tokens = shlex.split(raw.lstrip()[1:], comments=True)
                if not tokens or not tokens[-1].endswith(")"):
                    raise ValueError("array must open and close on one line")
                tokens[-1] = tokens[-1][:-1]
                if tokens[-1] == "":
                    tokens.pop()
                values[key] = [_coerce(key, t, element=True) for t in tokens]
            else:
                tokens = shlex.split(raw, comments=True)
                if len(tokens) > 1:
                    raise ValueError("unquoted value with spaces")
                values[key] = _coerce(key, tokens[0] if tokens else "")
        except ValueError as e:
            warnings.append(f"_config.sh line {lineno}: {e} in {key}, ignored")

    return values, warnings


def read_config_file(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Read a ``.json`` or ``.sh`` config file.

    Returns:
        (values, warnings)

    Raises:
        ConfigError: If a JSON file is malformed.
    """
    path = Path(path)
    if path.suffix == ".sh":
        return parse_config_sh(path.read_text(encoding="utf-8"))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: invalid JSON ({e})") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a JSON object at the top level")
    return data, []


class Config:
    """Configuration container with validation."""

    def __init__(self, config_dict: dict[str, Any]):
        """Initialize configuration from dictionary.

        Args:
            config_dict: Configuration dictionary.
        """
        self._config = config_dict
        # Notes produced while loading (e.g. _config.sh lines that were skipped)
        self.load_warnings: list[str] = []

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
            config_path: Explicit config file (``.json`` or ``.sh``). Must exist if given.
                Defaults to ``topdir/_config.json``, else expose.sh's ``topdir/_config.sh``.
            overrides: Values that take precedence over the file (e.g. from ``--set``).

        Returns:
            Config instance. ``load_warnings`` holds any notes for the user.

        Raises:
            ConfigError: If the config file is missing (when explicit) or not valid JSON.
        """
        config = dict(DEFAULT_CONFIG)
        warnings: list[str] = []

        if config_path is not None:
            config_path = Path(config_path)
            if not config_path.exists():
                raise ConfigError(f"Config file not found: {config_path}")
        else:
            config_path = find_config_file(Path(topdir))
            if config_path is not None and config_path.suffix == ".sh":
                warnings.append(
                    "Using _config.sh (expose.sh format); run `expose --convert-config` "
                    "to switch to _config.json"
                )

        if config_path is not None:
            user_config, file_warnings = read_config_file(config_path)
            warnings += file_warnings
            config.update(user_config)

        if overrides:
            config.update(overrides)

        result = cls(config)
        result.load_warnings = warnings
        return result

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

        warnings = []
        ffmpeg = c.get("ffmpeg", "auto")
        if not isinstance(ffmpeg, str) or not ffmpeg:
            errors.append(f"ffmpeg must be auto, bundled, system or a path, got {ffmpeg!r}")
        else:
            from dorothea.media.ffmpeg import FFMPEG_CHOICES, ffmpeg_exe

            if ffmpeg_exe(ffmpeg) is None:
                if ffmpeg in FFMPEG_CHOICES:
                    # Not fatal: galleries without videos don't need ffmpeg at all
                    warnings.append(
                        f"ffmpeg={ffmpeg!r}: no such ffmpeg available; videos will be skipped"
                    )
                else:
                    errors.append(
                        f"ffmpeg: {ffmpeg!r} is not an executable file (use auto, bundled, system or a path)"
                    )

        if topdir is not None:
            from dorothea.themes import resolve_theme_dir

            try:
                resolve_theme_dir(c.get("theme_dir", ""), Path(topdir))
            except FileNotFoundError as e:
                errors.append(str(e))

        if errors:
            raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errors))

        return warnings + [f"Unknown config key ignored: {k}" for k in c if k not in DEFAULT_CONFIG]

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

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value.

        Args:
            key: Configuration key.
            default: Default value if key not found.

        Returns:
            Configuration value or default.
        """
        return self._config.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Get configuration value using dict syntax.

        Args:
            key: Configuration key.

        Returns:
            Configuration value.

        Raises:
            KeyError: If key not found.
        """
        return self._config[key]

    def __setitem__(self, key: str, value: Any) -> None:
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
