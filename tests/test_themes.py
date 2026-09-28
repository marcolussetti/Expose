"""The photoessay and medium themes (#5, #16) and keyboard navigation."""

import shutil
import subprocess
from pathlib import Path

import pytest

from dorothea.config import EXPOSE_DEFAULTS
from dorothea.themes import BUNDLED_THEMES_DIR
from tests.conftest import make_generator, make_test_image

KEYBOARD_TEST = Path(__file__).parent / "js" / "keyboard_test.js"
PHOTO_INFO_TEST = Path(__file__).parent / "js" / "photo_info_test.js"


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


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_photo_info_js():
    """The ⓘ of exif_display: icon (#20); both themes ship the same file."""
    result = subprocess.run(
        ["node", str(PHOTO_INFO_TEST), str(BUNDLED_THEMES_DIR / "photoessay" / "photo-info.js")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_themes_share_one_photo_info_script():
    photoessay = (BUNDLED_THEMES_DIR / "photoessay" / "photo-info.js").read_bytes()
    assert photoessay == (BUNDLED_THEMES_DIR / "medium" / "photo-info.js").read_bytes()


def test_themes_share_one_keyboard_script():
    photoessay = (BUNDLED_THEMES_DIR / "photoessay" / "keyboard.js").read_bytes()
    assert photoessay == (BUNDLED_THEMES_DIR / "medium" / "keyboard.js").read_bytes()


@pytest.mark.parametrize("theme", ["photoessay", "medium"])
def test_icons_use_standard_css_masks(theme):
    """Sidebar icons are standard CSS masks: theme1's -webkit-mask-box-image draws plain squares
    in browsers that dropped it, and the $.browser sniffing that chose it is gone too."""
    folder = BUNDLED_THEMES_DIR / theme
    css = (folder / "global.css").read_text(encoding="utf-8")
    js = (folder / "global.js").read_text(encoding="utf-8")
    assert not any(
        "-webkit-mask-box-image:" in line for line in css.splitlines() if "/*" not in line
    )
    assert "$.browser" not in js and "jQuery.browser" not in js
    if theme == "photoessay":
        assert "mask-image: url(img/feed_mask.png)" in css


def test_photoessay_is_the_default_theme(tmp_path):
    html = build(tmp_path)
    assert '<script src="../keyboard.js" data-slides=".slide"></script>' in html
    assert (tmp_path / "_site" / "keyboard.js").exists()


def test_medium_navigates_between_items(tmp_path):
    html = build(tmp_path, theme_dir="medium")
    assert 'data-slides=".item"' in html
    assert 'data-blocked-by="#fullscreen.active, #fullscreenvideo.active"' in html
    assert html.count('<div class="item ') == 2


SMALL_SCREENS = "@media only screen and (max-width: 700px) {"


@pytest.mark.parametrize("theme", ["photoessay", "medium"])
def test_enhanced_themes_fit_small_screens(tmp_path, theme):
    """#5: phones lay the page out at their own width, and nothing forces it wider."""
    html = build(tmp_path, theme_dir=theme)
    assert '<meta name="viewport" content="width=device-width, initial-scale=1" />' in html
    css = (BUNDLED_THEMES_DIR / theme / "global.css").read_text(encoding="utf-8")
    small = css.split(SMALL_SCREENS, 1)[1]
    assert "min-width: 0;" in small


def test_photoessay_menu_button_only_on_small_screens(tmp_path):
    html = build(tmp_path)
    assert '<a href="#" id="menubutton" title="Galleries and settings">' in html
    css = (BUNDLED_THEMES_DIR / "photoessay" / "global.css").read_text(encoding="utf-8")
    desktop, small = css.split(SMALL_SCREENS, 1)
    assert "#menubutton{\ndisplay: none;\n}" in desktop
    assert "#menubutton{ display: block;" in small


@pytest.mark.parametrize("theme", ["theme1", "theme2"])
def test_original_themes_are_untouched(tmp_path, theme):
    """theme1/theme2 stay expose.sh-compatible: no keyboard script, no mobile layout (#5)."""
    html = build(tmp_path, theme_dir=theme)
    assert "keyboard.js" not in html
    assert not (BUNDLED_THEMES_DIR / theme / "keyboard.js").exists()
    assert 'name="viewport"' not in html


def test_legacy_uses_theme1():
    assert EXPOSE_DEFAULTS["theme_dir"] == "theme1"
