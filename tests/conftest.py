import json
import shutil
import subprocess
from pathlib import Path

import pytest

from expose import DEFAULT_CONFIG, ExposeGenerator

SCRIPTDIR = Path(__file__).resolve().parent.parent


def make_test_image(path, width=640, height=480, color="blue"):
    """Create a test image using ImageMagick convert."""
    subprocess.run(
        ["convert", "-size", f"{width}x{height}", f"xc:{color}", str(path)],
        check=True,
        capture_output=True,
    )


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
    config = dict(DEFAULT_CONFIG)
    config["extract_colors"] = True
    if config_overrides:
        config.update(config_overrides)
    return ExposeGenerator(topdir, SCRIPTDIR, config, draft=draft)


@pytest.fixture
def tmp_gallery(tmp_path):
    """Temp directory with a multi-level gallery tree, cleaned up after test."""
    make_gallery_tree(tmp_path)
    yield tmp_path
    # tmp_path cleanup is handled by pytest
