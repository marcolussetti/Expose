"""The photoessay and medium themes (#5, #16) and keyboard navigation."""

import shutil
import subprocess
from pathlib import Path

import pytest

from dorothea.config import EXPOSE_DEFAULTS
from dorothea.themes import BUNDLED_THEMES_DIR
from tests.conftest import make_generator, make_test_image

KEYBOARD_TEST = Path(__file__).parent / "js" / "keyboard_test.js"


def build(topdir, **overrides):
    (topdir / "g").mkdir()
    for name in ("a", "b"):
        make_test_image(topdir / "g" / f"{name}.jpg", 1200, 900, "red")
    make_generator(topdir, config_overrides=overrides or None).run()
    return (topdir / "_site" / "g" / "index.html").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.parametrize("theme", ["photoessay", "medium"])
def test_keyboard_navigation_js(theme):
    result = subprocess.run(
        ["node", str(KEYBOARD_TEST), str(BUNDLED_THEMES_DIR / theme / "keyboard.js")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_themes_share_one_keyboard_script():
    photoessay = (BUNDLED_THEMES_DIR / "photoessay" / "keyboard.js").read_bytes()
    assert photoessay == (BUNDLED_THEMES_DIR / "medium" / "keyboard.js").read_bytes()


def test_photoessay_is_the_default_theme(tmp_path):
    html = build(tmp_path)
    assert '<script src="../keyboard.js" data-slides=".slide"></script>' in html
    assert (tmp_path / "_site" / "keyboard.js").exists()


def test_medium_navigates_between_items(tmp_path):
    html = build(tmp_path, theme_dir="medium")
    assert 'data-slides=".item"' in html
    assert 'data-blocked-by="#fullscreen.active, #fullscreenvideo.active"' in html
    assert html.count('<div class="item ') == 2


@pytest.mark.parametrize("theme", ["theme1", "theme2"])
def test_original_themes_are_untouched(tmp_path, theme):
    """theme1/theme2 stay expose.sh-compatible: no keyboard script."""
    html = build(tmp_path, theme_dir=theme)
    assert "keyboard.js" not in html
    assert not (BUNDLED_THEMES_DIR / theme / "keyboard.js").exists()


def test_legacy_uses_theme1():
    assert EXPOSE_DEFAULTS["theme_dir"] == "theme1"
