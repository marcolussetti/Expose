"""Integration tests — require ImageMagick (convert/identify)."""

import json
import re
import shutil
from pathlib import Path

import pytest

from expose import DEFAULT_CONFIG, ExposeGenerator

from .conftest import SCRIPTDIR, make_gallery_tree, make_generator, make_test_image

pytestmark = pytest.mark.skipif(
    shutil.which("convert") is None or shutil.which("identify") is None,
    reason="ImageMagick not available",
)


# --- identify ---

def test_identify_dimensions(tmp_path):
    img = tmp_path / "test.jpg"
    make_test_image(img, 640, 480, "blue")
    gen = make_generator(tmp_path)
    assert gen.identify(img, "%w") == "640"
    assert gen.identify(img, "%h") == "480"
    gen.cleanup()


# --- scan_directories ---

def test_scan_directories_structure(tmp_gallery):
    gen = make_generator(tmp_gallery)
    gen.scan_directories()
    # Expect: topdir, Nature, Mountains, Oceans, Urban
    assert len(gen.paths) == 5
    # nav_name: topdir.name, Nature, Mountains, Oceans, Urban
    assert gen.nav_name[1] == "Nature"
    assert gen.nav_name[2] == "Mountains"
    assert gen.nav_name[3] == "Oceans"
    assert gen.nav_name[4] == "Urban"
    # nav_depth: 0, 1, 2, 2, 1
    assert gen.nav_depth == [0, 1, 2, 2, 1]
    # nav_type: 0 (topdir has subdirs), 0 (Nature has subdirs), 1, 1, 1
    assert gen.nav_type == [0, 0, 1, 1, 1]
    gen.cleanup()


def test_scan_directories_urls(tmp_gallery):
    gen = make_generator(tmp_gallery)
    gen.scan_directories()
    assert gen.nav_url[0] == "."
    assert gen.nav_url[1] == "nature"
    assert gen.nav_url[2] == "nature/mountains"
    assert gen.nav_url[3] == "nature/oceans"
    assert gen.nav_url[4] == "urban"
    gen.cleanup()


def test_scan_directories_skips_hidden(tmp_gallery):
    (tmp_gallery / ".hidden").mkdir()
    make_test_image(tmp_gallery / ".hidden" / "img.jpg")
    gen = make_generator(tmp_gallery)
    gen.scan_directories()
    names = [p.name for p in gen.paths]
    assert ".hidden" not in names
    gen.cleanup()


def test_scan_directories_skips_site(tmp_gallery):
    gen = make_generator(tmp_gallery)
    gen.scan_directories()
    names = [p.name for p in gen.paths]
    assert "_site" not in names
    gen.cleanup()


def test_scan_directories_skips_empty(tmp_gallery):
    (tmp_gallery / "03 Empty").mkdir()
    gen = make_generator(tmp_gallery)
    gen.scan_directories()
    names = gen.nav_name
    assert "Empty" not in names
    gen.cleanup()


# --- read_files ---

def _gen_with_files(tmp_gallery, config_overrides=None):
    gen = make_generator(tmp_gallery, config_overrides)
    gen.scan_directories()
    gen.read_files()
    return gen


def test_read_files_counts(tmp_gallery):
    gen = _gen_with_files(tmp_gallery)
    # Only leaf galleries (type==1) get counts: Mountains=1, Oceans=1, Urban=1
    leaf_counts = [gen.nav_count[i] for i in range(len(gen.paths)) if gen.nav_type[i] == 1]
    assert leaf_counts == [1, 1, 1]
    gen.cleanup()


def test_read_files_urls(tmp_gallery):
    gen = _gen_with_files(tmp_gallery)
    assert gen.gallery_url == ["peak", "wave", "city"]
    gen.cleanup()


def test_read_files_types(tmp_gallery):
    gen = _gen_with_files(tmp_gallery)
    assert all(t == 0 for t in gen.gallery_type)
    gen.cleanup()


def test_read_files_dimensions(tmp_gallery):
    gen = _gen_with_files(tmp_gallery)
    # Draft mode: resolution=[1024]
    # peak.jpg is 800x600 → below 1024, so falls through to last res (1024)
    #   maxwidth=1024, maxheight=1024*600//800=768
    assert gen.gallery_maxwidth[0] == 1024
    assert gen.gallery_maxheight[0] == 768
    # wave.jpg is 1200x800 → >=1024, so maxwidth=1024, maxheight=1024*800//1200=682
    assert gen.gallery_maxwidth[1] == 1024
    assert gen.gallery_maxheight[1] == 682
    # city.jpg is 640x480 → below 1024, falls to last → 1024, maxheight=1024*480//640=768
    assert gen.gallery_maxwidth[2] == 1024
    assert gen.gallery_maxheight[2] == 768
    gen.cleanup()


def test_read_files_color_extraction(tmp_gallery):
    gen = _gen_with_files(tmp_gallery)
    # Each gallery file should have a non-empty palette of hex colors
    for colors in gen.gallery_colors:
        assert len(colors) > 0
        for color in colors:
            assert re.match(r"^#[0-9A-Fa-f]+$", color)
    gen.cleanup()


def test_read_files_color_disabled(tmp_gallery):
    gen = _gen_with_files(tmp_gallery, config_overrides={"extract_colors": False})
    for colors in gen.gallery_colors:
        assert colors == list(DEFAULT_CONFIG["default_palette"])
    gen.cleanup()


# --- build_html ---

def _gen_with_html(tmp_gallery, config_overrides=None):
    gen = make_generator(tmp_gallery, config_overrides)
    gen.scan_directories()
    gen.read_files()
    gen.build_html()
    return gen


def test_build_html_generates_files(tmp_gallery):
    gen = _gen_with_html(tmp_gallery)
    site = tmp_gallery / "_site"
    assert (site / "index.html").exists()
    assert (site / "nature" / "mountains" / "index.html").exists()
    assert (site / "nature" / "oceans" / "index.html").exists()
    assert (site / "urban" / "index.html").exists()
    gen.cleanup()


def test_build_html_title(tmp_gallery):
    gen = _gen_with_html(tmp_gallery)
    site = tmp_gallery / "_site"
    html = (site / "nature" / "mountains" / "index.html").read_text()
    assert "<title>My Awesome Photos - Mountains</title>" in html
    html = (site / "urban" / "index.html").read_text()
    assert "<title>My Awesome Photos - Urban</title>" in html
    gen.cleanup()


def test_build_html_navigation_active(tmp_gallery):
    gen = _gen_with_html(tmp_gallery)
    site = tmp_gallery / "_site"
    html = (site / "nature" / "mountains" / "index.html").read_text()
    # The mountains gallery entry should have 'active'
    # Find the nav link for mountains and check it has active class
    assert re.search(r'class="gallery\s+active"[^>]*>.*?mountains', html, re.DOTALL)
    # Urban should NOT be active in mountains page
    urban_match = re.search(r'urban.*?class="gallery\s+active"', html, re.DOTALL)
    assert urban_match is None
    gen.cleanup()


def test_build_html_basepath(tmp_gallery):
    gen = _gen_with_html(tmp_gallery)
    site = tmp_gallery / "_site"
    # Mountains is depth 2, so basepath should be ../../
    html = (site / "nature" / "mountains" / "index.html").read_text()
    assert 'href="../../global.css"' in html
    # Urban is depth 1, so basepath should be ../
    html = (site / "urban" / "index.html").read_text()
    assert 'href="../global.css"' in html
    gen.cleanup()


def test_build_html_slide_count(tmp_gallery):
    gen = _gen_with_html(tmp_gallery)
    site = tmp_gallery / "_site"
    html = (site / "nature" / "mountains" / "index.html").read_text()
    assert html.count('class="slide"') == 1
    html = (site / "urban" / "index.html").read_text()
    assert html.count('class="slide"') == 1
    gen.cleanup()


def test_build_html_metadata_applied(tmp_gallery):
    gen = _gen_with_html(tmp_gallery)
    site = tmp_gallery / "_site"
    html = (site / "nature" / "mountains" / "index.html").read_text()
    # peak.txt has top: 60
    assert "top: 60%" in html
    gen.cleanup()


def test_build_html_defaults_applied(tmp_gallery):
    gen = _gen_with_html(tmp_gallery)
    site = tmp_gallery / "_site"
    # wave has no .txt file, so top should use default 70 from {{top:70}}
    html = (site / "nature" / "oceans" / "index.html").read_text()
    assert "top: 70%" in html
    gen.cleanup()


def test_build_html_no_leftover_vars(tmp_gallery):
    gen = _gen_with_html(tmp_gallery)
    site = tmp_gallery / "_site"
    for html_file in site.rglob("index.html"):
        html = html_file.read_text()
        leftover = re.findall(r"\{\{[^}]+\}\}", html)
        assert leftover == [], f"Leftover template vars in {html_file}: {leftover}"
    gen.cleanup()


# --- encode ---

def test_encode_images(tmp_gallery):
    gen = make_generator(tmp_gallery)
    gen.scan_directories()
    gen.read_files()
    gen.build_html()
    gen.encode_media()
    site = tmp_gallery / "_site"
    # Draft mode: resolution=[1024], so expect 1024.jpg for each image
    assert (site / "nature" / "mountains" / "peak" / "1024.jpg").exists()
    assert (site / "nature" / "oceans" / "wave" / "1024.jpg").exists()
    assert (site / "urban" / "city" / "1024.jpg").exists()
    gen.cleanup()


def test_encode_images_idempotent(tmp_gallery):
    gen = make_generator(tmp_gallery)
    gen.scan_directories()
    gen.read_files()
    gen.build_html()
    gen.encode_media()
    site = tmp_gallery / "_site"
    img = site / "nature" / "mountains" / "peak" / "1024.jpg"
    mtime1 = img.stat().st_mtime
    # Run encode again with a fresh generator
    gen2 = make_generator(tmp_gallery)
    gen2.scan_directories()
    gen2.read_files()
    gen2.build_html()
    gen2.encode_media()
    mtime2 = img.stat().st_mtime
    assert mtime1 == mtime2
    gen.cleanup()
    gen2.cleanup()


# --- config override ---

def test_config_override(tmp_gallery):
    config = {"site_title": "Custom Title"}
    (tmp_gallery / "_config.json").write_text(json.dumps(config))

    from expose import load_config

    loaded = load_config(tmp_gallery, SCRIPTDIR)
    assert loaded["site_title"] == "Custom Title"
    # Other defaults preserved
    assert loaded["jpeg_quality"] == 92


# --- full pipeline ---

def test_full_pipeline(tmp_gallery):
    gen = make_generator(tmp_gallery)
    gen.run()
    site = tmp_gallery / "_site"
    assert (site / "index.html").exists()
    assert (site / "nature" / "mountains" / "index.html").exists()
    assert (site / "nature" / "oceans" / "index.html").exists()
    assert (site / "urban" / "index.html").exists()
    assert (site / "nature" / "mountains" / "peak" / "1024.jpg").exists()
    # Theme resources copied
    assert (site / "global.css").exists()
