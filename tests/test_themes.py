"""Dorothea's themes (#5, #16, #28) and keyboard navigation."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from dorothea.config import EXPOSE_DEFAULTS
from dorothea.themes import BUNDLED_THEMES_DIR
from tests.conftest import make_generator, make_test_image

KEYBOARD_TEST = Path(__file__).parent / "js" / "keyboard_test.js"
PHOTO_INFO_TEST = Path(__file__).parent / "js" / "photo_info_test.js"
CONTACTSHEET_TEST = Path(__file__).parent / "js" / "contactsheet_test.js"

# Dorothea's own themes, which share keyboard.js and photo-info.js
THEMES = ["photoessay", "medium", "contactsheet"]


def build(topdir, files=None, **overrides):
    """A gallery ``g`` with photos a and b, plus ``files`` (name -> text) next to them."""
    (topdir / "g").mkdir()
    for name in ("a", "b"):
        make_test_image(topdir / "g" / f"{name}.jpg", 1200, 900, "red")
    for name, text in (files or {}).items():
        (topdir / "g" / name).write_text(text, encoding="utf-8")
    make_generator(topdir, config_overrides=overrides or None).run()
    return (topdir / "_site" / "g" / "index.html").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.parametrize("theme", THEMES)
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


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_contactsheet_js():
    """The grid and lightbox of contactsheet (#28)."""
    result = subprocess.run(
        [
            "node",
            str(CONTACTSHEET_TEST),
            str(BUNDLED_THEMES_DIR / "contactsheet" / "contactsheet.js"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("script", ["keyboard.js", "photo-info.js"])
def test_themes_share_one_copy_of_scripts(script):
    photoessay = (BUNDLED_THEMES_DIR / "photoessay" / script).read_bytes()
    for theme in THEMES[1:]:
        assert (BUNDLED_THEMES_DIR / theme / script).read_bytes() == photoessay, theme


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


@pytest.mark.parametrize("theme", THEMES)
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


class TestContactsheet:
    """The masonry grid theme (#28)."""

    def test_builds_a_grid_of_tiles(self, tmp_path):
        html = build(tmp_path, theme_dir="contactsheet")
        assert html.count('<figure class="tile caption-overlay" id="') == 2
        assert (
            '<script src="../keyboard.js" data-slides="" data-blocked-by="#lightbox[open]">' in html
        )
        assert '<dialog id="lightbox"' in html
        assert "jquery" not in html.lower()
        assert "{{" not in html
        for name in ("contactsheet.js", "keyboard.js", "photo-info.js", "global.css"):
            assert (tmp_path / "_site" / name).is_file()
        # snippets are read by the builder, not published
        assert not (tmp_path / "_site" / "post-template.html").exists()

    def test_images_exist_are_lazy_and_sized(self, tmp_path):
        html = build(tmp_path, theme_dir="contactsheet")
        images = re.findall(r"<img [^>]*>", html)
        assert len(images) == 2
        for img in images:
            assert 'loading="lazy"' in img
            assert re.search(r'width="\d+" height="\d+"', img)
            src = re.search(r'src="([^"]+)"', img)[1]
            srcset = re.search(r'srcset="([^"]+)"', img)[1]
            urls = [src] + [part.split()[0] for part in srcset.split(", ")]
            for url in urls:
                assert (tmp_path / "_site" / "g" / url).is_file(), url

    def test_top_level_page_points_into_the_gallery(self, tmp_path):
        build(tmp_path, theme_dir="contactsheet")
        html = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
        for url in re.findall(r'(?:src|srcset)="([^"]+?\.jpg)', html):
            assert url.startswith("g/") and (tmp_path / "_site" / url).is_file(), url

    def test_srcset_lists_the_widths_made(self, tmp_path):
        """{{srcset}}: widths up to the photo's own, or just the smallest for a small photo."""
        (tmp_path / "g").mkdir()
        make_test_image(tmp_path / "g" / "big.jpg", 1300, 975, "red")
        make_test_image(tmp_path / "g" / "small.jpg", 300, 200, "red")
        gen = make_generator(
            tmp_path,
            {"theme_dir": "contactsheet", "resolution": [1920, 1280, 640, 320]},
            draft=False,
        )
        gen.scan_directories()
        gen.read_files()
        gen.build_html()
        gen.cleanup()
        html = (tmp_path / "_site" / "g" / "index.html").read_text(encoding="utf-8")
        assert re.findall(r'srcset="([^"]+)"', html) == [
            "big/320.jpg 320w, big/640.jpg 640w, big/1280.jpg 1280w",
            "small/320.jpg 320w",
        ]

    def test_captions_below_from_the_config(self, tmp_path):
        html = build(tmp_path, theme_dir="contactsheet", caption_position="below")
        assert html.count('class="tile caption-below"') == 2

    def test_captions_position_per_gallery_and_photo(self, tmp_path):
        html = build(
            tmp_path,
            files={
                "gallery.yml": "caption_position: below\n",
                "a.md": "---\ncaption_position: overlay\n---\nHello\n",
            },
            theme_dir="contactsheet",
        )
        # a's caption wins over the gallery's, which wins over the config's
        assert re.findall(r'class="tile caption-(\w+)"', html) == ["overlay", "below"]

    def test_caption_text_is_in_the_tile(self, tmp_path):
        html = build(tmp_path, files={"a.md": "Hello *there*\n"}, theme_dir="contactsheet")
        tile = html.split('<figure class="tile')[1]
        assert '<figcaption class="caption"> <p>Hello <em>there</em></p>' in tile


@pytest.mark.parametrize("theme", ["theme1", "theme2"])
def test_original_themes_are_untouched(tmp_path, theme):
    """theme1/theme2 stay expose.sh-compatible: no keyboard script, no mobile layout (#5)."""
    html = build(tmp_path, theme_dir=theme)
    assert "keyboard.js" not in html
    assert not (BUNDLED_THEMES_DIR / theme / "keyboard.js").exists()
    assert 'name="viewport"' not in html


def test_legacy_uses_theme1():
    assert EXPOSE_DEFAULTS["theme_dir"] == "theme1"
