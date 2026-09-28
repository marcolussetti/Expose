"""The JSON Schema behind the docs' configurator and editor completion (#30)."""

import json
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest

from dorothea.config import DEFAULT_CONFIG, EXPOSE_DEFAULTS, Config, ConfigError
from scripts.build_schema import DOCS_PAGE, ROOT, SCHEMA_URL, _page_links, build_schema

CONFIGURATOR = ROOT / "docs" / "configurator.js"
CONFIGURATOR_TEST = ROOT / "tests" / "js" / "configurator_test.js"
PAGE = DOCS_PAGE.read_text(encoding="utf-8")
SCHEMA = build_schema(PAGE)
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def schema_errors(config: dict) -> list[str]:
    return [error.message for error in VALIDATOR.iter_errors(config)]


def validate(config: dict) -> list[str]:
    """Config.validate() on the defaults plus ``config`` (like Config.load)."""
    return Config({**DEFAULT_CONFIG, **config}).validate()


def test_schema_is_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["$id"] == SCHEMA_URL


def test_every_setting_with_both_defaults():
    properties = SCHEMA["properties"]
    assert set(properties) - {"$schema"} == set(DEFAULT_CONFIG)
    for key, prop in properties.items():
        if key != "$schema":
            assert prop["default"] == DEFAULT_CONFIG[key], key
            assert prop["x-legacy-default"] == EXPOSE_DEFAULTS[key], key
            assert prop["x-section"] and prop["description"], key


def test_properties_follow_the_docs_order():
    order = [key for key in SCHEMA["properties"] if key != "$schema"]
    assert order[:2] == ["site_title", "theme_dir"]  # the first table, "Site and theme"
    assert SCHEMA["properties"]["jpeg_quality"]["x-section"] == "Images"


@pytest.mark.parametrize("defaults", [DEFAULT_CONFIG, EXPOSE_DEFAULTS], ids=["dorothea", "legacy"])
def test_both_default_sets_fit_the_schema(defaults):
    assert schema_errors(dict(defaults)) == []


@pytest.mark.parametrize(
    "config",
    [
        {"$schema": SCHEMA_URL, "site_title": "Iceland", "theme_dir": "medium"},
        {"resolution": [2560, 640], "bitrate": [12.5, 2], "jpeg_quality": 100},
        {"video_formats": ["vp9", "h264"], "sort": "capture-desc", "keep_metadata": "none"},
        {"site_url": "https://example.com/photos/", "exif_display": "caption", "legacy": True},
        {"site_url": "", "ffmpeg": "bundled", "jobs": 0, "download_album": True},
    ],
)
def test_what_the_schema_accepts_builds(config):
    """A config the configurator can produce passes Config.validate() without warnings."""
    assert schema_errors(config) == []
    # (a machine without the chosen ffmpeg gets a warning about that, which is fine here)
    assert [w for w in validate(config) if "ffmpeg" not in w] == []


@pytest.mark.parametrize(
    "config",
    [
        {"jpeg_quality": 0},
        {"jpeg_quality": "90"},
        {"resolution": []},
        {"resolution": [0]},
        {"resolution": [1920.5]},
        {"bitrate": [0]},
        {"bitrate_maxratio": 0.5},
        {"video_formats": ["av1"]},
        {"sort": "random"},
        {"keep_metadata": "gps"},
        {"exif_display": "yes"},
        {"site_url": "example.com"},
        {"legacy": "yes"},
        {"download_album": "yes"},
        {"jobs": -1},
    ],
)
def test_what_the_schema_rejects_fails_the_build(config):
    """The schema is at least as strict as Config.validate(), so the page catches these."""
    assert schema_errors(config)
    with pytest.raises(ConfigError):
        validate(config)


def test_unknown_keys():
    """Typos are flagged by the schema; Dorothea only warns about them."""
    assert schema_errors({"site_titel": "x"})
    assert validate({"site_titel": "x"}) == [
        "Unknown setting site_titel ignored; did you mean site_title?"
    ]


def test_schema_key_is_not_an_unknown_setting():
    assert not any("$schema" in w for w in validate({"$schema": SCHEMA_URL}))


def test_descriptions_are_html_with_site_links():
    theme = SCHEMA["properties"]["theme_dir"]["description"]
    assert "<code>photoessay</code>" in theme and "`" not in theme
    legacy = SCHEMA["properties"]["legacy"]["description"]
    assert 'href="#legacy-exposesh-defaults"' in legacy


def test_page_links():
    assert _page_links('<a href="galleries.md#metadata-keys">') == (
        '<a href="../galleries/#metadata-keys">'
    )
    assert _page_links('<a href="index.md#preview">') == '<a href="../#preview">'
    assert _page_links('<a href="#same-page">') == '<a href="#same-page">'


def test_docs_and_code_must_agree():
    page = PAGE.replace("| `jpeg_quality` |", "| `jpeg_qualty` |")
    with pytest.raises(SystemExit, match=r"undocumented \['jpeg_quality'\].*\['jpeg_qualty'\]"):
        build_schema(page)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_configurator_js(tmp_path):
    """The configurator's logic (docs/configurator.js) against the real schema."""
    schema = tmp_path / "config.json"
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    result = subprocess.run(
        ["node", str(CONFIGURATOR_TEST), str(CONFIGURATOR), str(schema)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_script_writes_the_file(tmp_path, monkeypatch):
    from scripts import build_schema as script

    out = tmp_path / "schema" / "config.json"
    monkeypatch.setattr("sys.argv", ["build_schema.py", str(out)])
    script.main()
    assert Path(out).read_text(encoding="utf-8").startswith("{\n")
