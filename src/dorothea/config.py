"""Configuration management for Dorothea.

Loads ``_config.yml`` (or expose.sh's ``_config.sh``) over the defaults, and validates the
result, naming the file and line of each problem.
"""

import difflib
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, TypeIs

from dorothea.yamlfile import YamlError, load_mapping

# Config files looked for in the gallery folder, in order (#46): YAML, else expose.sh's format
CONFIG_FILES = ("_config.yml", "_config.yaml", "_config.sh")

# Video format -> container extension
VIDEO_FORMAT_EXTENSIONS = {"h264": "mp4", "h265": "mp4", "vp9": "webm", "vp8": "webm", "ogv": "ogv"}

# expose.sh's defaults: with these (`--legacy`), a fresh build matches expose.sh's output
EXPOSE_DEFAULTS = {
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
    # Dorothea-only: one zip per gallery with all its originals (#9)
    "download_album": False,
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
    # Dorothea-only: order of galleries and photos, see dorothea.sorting.SORT_MODES
    "sort": "name",
    # Dorothea-only: convert wide-gamut (non-sRGB) photos to sRGB; expose.sh strips the profile
    "convert_to_srgb": False,
    # Dorothea-only: EXIF kept in resized images, see media.metadata.KEEP_METADATA_LEVELS
    "keep_metadata": "none",
    # Dorothea-only: link galleries to .../index.html, so the site also works opened from disk
    "link_index_html": False,
    # Dorothea-only: the site's public address (https://…); when set, writes an Atom feed.xml
    "site_url": "",
    # Dorothea-only: with site_url, each gallery also gets its own feed.xml (one entry per photo)
    "gallery_feeds": True,
    # Dorothea-only: show photos' camera/lens/exposure from EXIF (#20), see EXIF_DISPLAY_MODES
    "exif_display": "off",
    # Dorothea-only: use these expose.sh defaults instead of DOROTHEA_DEFAULTS
    "legacy": True,
}

# Where Dorothea's own defaults differ from expose.sh's (#24)
DOROTHEA_CHANGES = {
    "theme_dir": "photoessay",  # theme1 + improvements (keyboard navigation, #16); #5
    "sort": "natural",  # 1, 2, 10 without zero-padding
    "video_formats": ["h264", "vp9"],  # vp9: much smaller than vp8, supported by every browser
    "h264_encodespeed": "slow",  # ~2-3x faster than veryslow for a few percent larger files
    "social_button": False,  # the 2015-era share menu is opt-in
    "convert_to_srgb": True,  # Display P3 / Adobe RGB photos keep their colours (#12)
    "keep_metadata": "camera",  # copyright + camera settings; never location unless asked (#12)
    "exif_display": "icon",  # photo details behind an ⓘ, in themes that support it (#20)
    "legacy": False,
}

# exif_display (#20): nothing, an ⓘ with a details panel on each photo, or a line under its text
EXIF_DISPLAY_MODES = ("off", "icon", "caption")

# x264/x265 presets, fastest to slowest (h264_encodespeed)
H264_PRESETS = (
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow", "placebo",
)  # fmt: skip

# What a setting's default doesn't say about it, for the JSON Schema that editors and the docs'
# configurator use (scripts/build_schema.py; types, defaults and descriptions come from
# DOROTHEA_DEFAULTS / EXPOSE_DEFAULTS and docs/configuration.md). JSON Schema keywords, plus
# "x-input": "color" for CSS colours. Choices defined elsewhere (sort, keep_metadata, ffmpeg,
# themes, video formats) are added by the script.
SETTING_HINTS: dict[str, dict[str, Any]] = {
    "resolution": {"minItems": 1, "items": {"minimum": 1}},
    "jpeg_quality": {"minimum": 1, "maximum": 100},
    # whole-number defaults, but any positive number works
    "bitrate": {"minItems": 1, "items": {"type": "number", "exclusiveMinimum": 0}},
    "bitrate_maxratio": {"minimum": 1},
    "backgroundcolor": {"x-input": "color"},
    "textcolor": {"x-input": "color"},
    "default_palette": {"items": {"x-input": "color"}},
    "h264_encodespeed": {"enum": list(H264_PRESETS)},
    "vp9_encodespeed": {"minimum": 0, "maximum": 4},
    "ffmpeg_threads": {"minimum": 0},
    "jobs": {"minimum": 0},
    "sequence_framerate": {"exclusiveMinimum": 0},
    "exif_display": {"enum": list(EXIF_DISPLAY_MODES)},
    "site_url": {"pattern": r'^(https?://[^\s"<>]+)?$'},
}

# Keys a config file may have that aren't settings: "$schema" points editors at the JSON Schema
NON_SETTING_KEYS = {"$schema"}

DOROTHEA_DEFAULTS = {**EXPOSE_DEFAULTS, **DOROTHEA_CHANGES}

# The defaults (Dorothea's); `--legacy` / "legacy": true switches to EXPOSE_DEFAULTS
DEFAULT_CONFIG = DOROTHEA_DEFAULTS


def is_int(value: object) -> TypeIs[int]:
    """True for ints but not bools (``True`` is an int in Python)."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value: object) -> TypeIs[int | float]:
    """True for ints and floats but not bools."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class ConfigError(ValueError):
    """Raised when the configuration is malformed or has invalid values."""


def find_config_file(topdir: Path) -> Path | None:
    """The first of ``CONFIG_FILES`` in ``topdir``, else None.

    Raises:
        ConfigError: For a ``_config.json`` from Dorothea 1.9 (read before #46), so its settings
            aren't silently ignored.
    """
    for name in CONFIG_FILES:
        candidate = topdir / name
        if candidate.exists():
            return candidate
    if (topdir / "_config.json").exists():
        raise ConfigError(_JSON_HINT)
    return None


_JSON_HINT = (
    "Settings now go in _config.yml: rename _config.json to _config.yml "
    "(JSON is valid YAML, so it works as it is)"
)


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


def read_config_file(path: Path) -> tuple[dict[str, Any], list[str], dict[str, int]]:
    """Read a ``.yml``/``.yaml`` or expose.sh ``.sh`` config file.

    Returns:
        (values, warnings, key -> line number); ``.sh`` files have no line numbers.

    Raises:
        ConfigError: If a YAML file can't be read, or the file is of another kind.
    """
    path = Path(path)
    if path.suffix == ".sh":
        values, warnings = parse_config_sh(path.read_text(encoding="utf-8"))
        return values, warnings, {}
    if path.suffix not in (".yml", ".yaml"):
        hint = _JSON_HINT if path.suffix == ".json" else "use a .yml file (or expose.sh's .sh)"
        raise ConfigError(f"{path}: {hint}")
    try:
        values, lines = load_mapping(path.read_text(encoding="utf-8"))
    except YamlError as e:
        raise ConfigError(f"{path.name} {e}") from e

    # `key:` with nothing after it: most likely a placeholder, so the default applies
    warnings = [
        f"{key} has no value in {path.name} (line {lines.get(key)}); using the default"
        for key, value in values.items()
        if value is None
    ]
    return {k: v for k, v in values.items() if v is not None}, warnings, lines


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
        # Where settings from a config file were written, e.g. "_config.yml line 3", so
        # validate() can point at them
        self.sources: dict[str, str] = {}

    @classmethod
    def load(
        cls,
        topdir: Path,
        scriptdir: Path,
        config_path: Path | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> Config:
        """Load configuration: defaults, then the config file, then overrides.

        The defaults are Dorothea's, or expose.sh's when ``legacy`` is true (in the overrides,
        e.g. ``--legacy``, or else in the config file).

        Args:
            topdir: Top-level directory (where _config.yml might be).
            scriptdir: Script directory (for resolving theme paths).
            config_path: Explicit config file (``.yml`` or ``.sh``). Must exist if given.
                Defaults to the first of ``CONFIG_FILES`` in ``topdir``.
            overrides: Values that take precedence over the file (e.g. from ``--set``).

        Returns:
            Config instance. ``load_warnings`` holds any notes for the user, ``sources`` the
            line each file setting came from.

        Raises:
            ConfigError: If the config file is missing (when explicit) or can't be read.
        """
        user_config: dict[str, Any] = {}
        overrides = overrides or {}
        warnings: list[str] = []
        lines: dict[str, int] = {}

        if config_path is not None:
            config_path = Path(config_path)
            if not config_path.exists():
                raise ConfigError(f"Config file not found: {config_path}")
        else:
            config_path = find_config_file(Path(topdir))
            if config_path is not None and config_path.suffix == ".sh":
                warnings.append(
                    "Using _config.sh (expose.sh format); run `dorothea --convert-config` "
                    "to switch to _config.yml"
                )

        if config_path is not None:
            user_config, file_warnings, lines = read_config_file(config_path)
            warnings += file_warnings

        legacy = overrides.get("legacy", user_config.get("legacy", False))
        config = dict(EXPOSE_DEFAULTS if legacy is True else DOROTHEA_DEFAULTS)
        config.update(user_config)
        config.update(overrides)

        result = cls(config)
        result.load_warnings = warnings
        if config_path is not None:
            result.sources = {
                key: f"{config_path.name} line {line}"
                for key, line in lines.items()
                if key in user_config and key not in overrides
            }
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

        from dorothea.sorting import SORT_MODES

        sort = c.get("sort", "name")
        if sort not in SORT_MODES:
            errors.append(f"sort must be one of {', '.join(SORT_MODES)}; got {sort!r}")

        legacy = c.get("legacy", False)
        if not isinstance(legacy, bool):
            errors.append(f"legacy must be true or false, got {legacy!r}")

        for key in ("convert_to_srgb", "link_index_html", "gallery_feeds", "download_album"):
            if not isinstance(c.get(key, False), bool):
                errors.append(f"{key} must be true or false, got {c[key]!r}")

        site_url = c.get("site_url", "")
        if not isinstance(site_url, str) or (
            site_url and not re.fullmatch(r"https?://[^\s\"<>]+", site_url)
        ):
            errors.append(
                f"site_url must be the site's address, like https://example.com/photos/ "
                f"(or empty), got {site_url!r}"
            )

        from dorothea.media.metadata import KEEP_METADATA_LEVELS

        keep = c.get("keep_metadata", "none")
        if keep not in KEEP_METADATA_LEVELS:
            levels = ", ".join(KEEP_METADATA_LEVELS)
            errors.append(f"keep_metadata must be one of {levels}; got {keep!r}")

        exif_display = c.get("exif_display", "off")
        if exif_display not in EXIF_DISPLAY_MODES:
            modes = ", ".join(EXIF_DISPLAY_MODES)
            errors.append(f"exif_display must be one of {modes}; got {exif_display!r}")

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
                errors.append(f"theme_dir: {e}")

        if errors:
            errors = [self._located(error) for error in errors]
            raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errors))

        return warnings + [
            self._unknown(k) for k in c if k not in DEFAULT_CONFIG and k not in NON_SETTING_KEYS
        ]

    def _located(self, message: str) -> str:
        """``message`` about a setting (it starts with its name), plus the line it's on."""
        key = re.match(r"\w+", message)
        source = self.sources.get(key.group()) if key else None
        return f"{message} ({source})" if source else message

    def _unknown(self, key: str) -> str:
        """The warning for an unknown key, suggesting the setting it's probably a typo of."""
        source = self.sources.get(key)
        message = f"Unknown setting {key} ignored" + (f" ({source})" if source else "")
        close = difflib.get_close_matches(key, list(DEFAULT_CONFIG), n=1, cutoff=0.75)
        return message + (f"; did you mean {close[0]}?" if close else "")

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
        self._config["download_album"] = False

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
