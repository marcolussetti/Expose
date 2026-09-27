"""Write the JSON Schema of ``_config.json`` for the docs site (#30).

The schema drives the configurator on docs/configuration.md, and ``"$schema"`` in a
``_config.json`` gives editors (VS Code, …) completion and checks. Nothing about a setting is
written twice: keys, types and defaults come from ``config.DOROTHEA_DEFAULTS`` /
``EXPOSE_DEFAULTS``, choices from the constants the code already uses, ranges from
``config.SETTING_HINTS``, and sections and descriptions from the settings tables in
docs/configuration.md.

    uv run python scripts/build_schema.py [OUTPUT]   # default: docs/schema/config.json
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

import markdown

from dorothea.config import (
    DOROTHEA_DEFAULTS,
    EXPOSE_DEFAULTS,
    SETTING_HINTS,
    VIDEO_FORMAT_EXTENSIONS,
)
from dorothea.media.ffmpeg import FFMPEG_CHOICES
from dorothea.media.metadata import KEEP_METADATA_LEVELS
from dorothea.sorting import SORT_MODES
from dorothea.themes import BUNDLED_THEMES_DIR

ROOT = Path(__file__).resolve().parent.parent
DOCS_PAGE = ROOT / "docs" / "configuration.md"
OUTPUT = ROOT / "docs" / "schema" / "config.json"
SCHEMA_URL = "https://dorothea.readthedocs.io/schema/config.json"

_TABLE_HEADER = "| Key | Default | Description |"
_ROW = re.compile(r"^\| `(?P<key>[^`]+)` \| (?P<default>.*?) \| (?P<description>.*) \|$")


def documented_settings(page: str) -> dict[str, tuple[str, str]]:
    """``key -> (section, Markdown description)`` from the page's settings tables, in order."""
    settings: dict[str, tuple[str, str]] = {}
    section, in_table = "", False
    for line in page.splitlines():
        if line.startswith("## "):
            section, in_table = line[3:].strip(), False
        elif line.strip() == _TABLE_HEADER:
            in_table = True
        elif in_table and (match := _ROW.match(line)):
            settings[match["key"]] = (section, match["description"])
        elif in_table and not line.startswith("|"):
            in_table = False
    return settings


def _page_links(html: str) -> str:
    """Links as written in the docs (``galleries.md#x``) → as served (``../galleries/#x``),
    since descriptions are shown on the configuration page. Same-page ``#anchors`` stay."""

    def rewrite(match: re.Match[str]) -> str:
        page, anchor = match["page"], match["anchor"] or ""
        path = "../" if page == "index" else f"../{page}/"
        return f'href="{path}{anchor}"'

    return re.sub(r'href="(?P<page>[\w-]+)\.md(?P<anchor>#[^"]*)?"', rewrite, html)


def _describe(text: str) -> str:
    html = markdown.markdown(text)
    return _page_links(html.removeprefix("<p>").removesuffix("</p>"))


def _type(value: Any) -> dict[str, Any]:
    """JSON Schema type of a default value (lists: of their first item's type)."""
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, list):
        return {"type": "array", "items": _type(value[0]) if value else {}}
    return {"type": "string"}


def _choices() -> dict[str, dict[str, Any]]:
    """Choices for settings whose values are defined elsewhere in the code."""
    themes = sorted(p.name for p in BUNDLED_THEMES_DIR.iterdir() if p.is_dir())
    return {
        "sort": {"enum": list(SORT_MODES)},
        "keep_metadata": {"enum": list(KEEP_METADATA_LEVELS)},
        "video_formats": {"items": {"enum": list(VIDEO_FORMAT_EXTENSIONS)}, "uniqueItems": True},
        # A path works too, so these are suggestions rather than an enum
        "ffmpeg": {"examples": list(FFMPEG_CHOICES), "minLength": 1},
        "theme_dir": {"examples": themes},
    }


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def build_schema(page: str) -> dict[str, Any]:
    """The schema, with properties in the order the docs list them."""
    documented = documented_settings(page)
    missing = [key for key in DOROTHEA_DEFAULTS if key not in documented]
    extra = [key for key in documented if key not in DOROTHEA_DEFAULTS]
    if missing or extra:
        raise SystemExit(
            f"docs/configuration.md and config.py disagree: undocumented {missing}, "
            f"documented but unknown {extra}"
        )

    choices = _choices()
    properties: dict[str, Any] = {
        "$schema": {"type": "string", "description": "The schema this file follows."}
    }
    for key, (section, description) in documented.items():
        prop = _type(DOROTHEA_DEFAULTS[key])
        prop = _merge(prop, choices.get(key, {}))
        prop = _merge(prop, SETTING_HINTS.get(key, {}))
        prop |= {
            "default": DOROTHEA_DEFAULTS[key],
            "x-legacy-default": EXPOSE_DEFAULTS[key],
            "x-section": section,
            "description": _describe(description),
        }
        properties[key] = prop

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URL,
        "title": "Dorothea _config.json",
        "description": "Settings for Dorothea, https://dorothea.readthedocs.io/configuration/",
        "type": "object",
        "properties": properties,
        # Unknown keys are ignored (with a warning) by Dorothea, and are usually typos
        "additionalProperties": False,
    }


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT
    schema = build_schema(DOCS_PAGE.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {output.relative_to(ROOT) if output.is_relative_to(ROOT) else output}")


if __name__ == "__main__":
    main()
