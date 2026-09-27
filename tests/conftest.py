import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from dorothea.config import DEFAULT_CONFIG, Config
from dorothea.generator import ExposeGenerator
from dorothea.media.imagemagick import imagemagick_command

# Directory containing the bash reference implementation (expose.sh) and its
# dependencies. Used only by parity tests.
REFDIR = Path(__file__).resolve().parent / "reference"

# Directory containing test gallery data (test_run/, etc.)
DATADIR = Path(__file__).resolve().parent / "data"

# Project root — passed as scriptdir to ExposeGenerator for legacy
# compatibility. Themes are resolved via resolve_theme_dir() so the actual
# value no longer affects theme loading.
SCRIPTDIR = Path(__file__).resolve().parent.parent

# Real ImageMagick (not Windows' System32 convert.exe); see dorothea.media.imagemagick
HAS_IMAGEMAGICK = imagemagick_command() is not None


def make_test_image(path, width=640, height=480, color="blue"):
    """Create a solid-colour test image.

    Uses ImageMagick when installed: the parity tests' expected output depends on the exact
    input bytes. Falls back to Pillow so the rest of the suite runs without system packages.
    """
    if shutil.which("magick"):
        subprocess.run(
            ["magick", "-size", f"{width}x{height}", f"xc:{color}", str(path)],
            check=True,
            capture_output=True,
        )
    else:
        Image.new("RGB", (width, height), color).save(path)


def make_gallery_tree(base_dir):
    """Create a multi-level gallery tree with test images.

    Structure:
        base_dir/
            01 Nature/
                01 Mountains/
                    01 peak.jpg (800x600, blue)
                    01 peak.txt (metadata with top: 60)
                02 Oceans/
                    01 wave.jpg (1200x800, green)
            02 Urban/
                01 city.jpg (640x480, red)
    """
    base = Path(base_dir)

    mountains = base / "01 Nature" / "01 Mountains"
    mountains.mkdir(parents=True)
    make_test_image(mountains / "01 peak.jpg", 800, 600, "blue")
    (mountains / "01 peak.txt").write_text("title: Peak\ntop: 60\n---\nA mountain peak.")

    oceans = base / "01 Nature" / "02 Oceans"
    oceans.mkdir(parents=True)
    make_test_image(oceans / "01 wave.jpg", 1200, 800, "green")

    urban = base / "02 Urban"
    urban.mkdir(parents=True)
    make_test_image(urban / "01 city.jpg", 640, 480, "red")


def make_generator(topdir, config_overrides=None, draft=True):
    """Create an ExposeGenerator with fast defaults for testing.

    Uses draft=True by default (resolution=[1024], single format).
    """
    config_dict = dict(DEFAULT_CONFIG)
    config_dict["extract_colors"] = True
    if config_overrides:
        config_dict.update(config_overrides)
    config = Config(config_dict)
    if draft:
        config.apply_draft_mode()
    return ExposeGenerator(topdir, SCRIPTDIR, config, draft=draft)


@pytest.fixture
def tmp_gallery(tmp_path):
    """Temp directory with a multi-level gallery tree, cleaned up after test."""
    make_gallery_tree(tmp_path)
    yield tmp_path
    # tmp_path cleanup is handled by pytest


@pytest.fixture(autouse=True)
def _reset_ffmpeg_choice():
    """The ffmpeg choice is module-level state; don't let one test's choice leak into another."""
    from dorothea.media.ffmpeg import set_ffmpeg

    yield
    set_ffmpeg("auto")


@pytest.fixture(autouse=True)
def _reset_imagemagick_lookup():
    """The ImageMagick lookup is cached; a test that mocks it mustn't leak into others."""
    yield
    imagemagick_command.cache_clear()
