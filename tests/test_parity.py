"""Parity tests — compare expose.sh vs expose.py output.

These tests run both generators on the same gallery and verify identical output.
Marked as slow since they invoke two full pipeline runs.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from .conftest import SCRIPTDIR, make_gallery_tree

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        shutil.which("convert") is None or shutil.which("identify") is None,
        reason="ImageMagick not available",
    ),
    pytest.mark.skipif(
        shutil.which("bash") is None,
        reason="bash not available",
    ),
    pytest.mark.skipif(
        not (SCRIPTDIR / "expose.sh").exists(),
        reason="expose.sh not found",
    ),
]


@pytest.fixture(scope="session")
def parity_outputs(tmp_path_factory):
    """Run both expose.sh and expose.py on the same gallery, return (shell_dir, python_dir)."""
    gallery = tmp_path_factory.mktemp("gallery")
    make_gallery_tree(gallery)

    shell_output = tmp_path_factory.mktemp("shell_output")
    python_output = tmp_path_factory.mktemp("python_output")

    # Run shell version
    subprocess.run(
        ["bash", str(SCRIPTDIR / "expose.sh"), "-d"],
        cwd=str(gallery),
        check=True,
        capture_output=True,
    )
    # Copy _site to shell_output
    for item in (gallery / "_site").iterdir():
        dest = shell_output / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    shutil.rmtree(gallery / "_site")

    # Run Python version
    subprocess.run(
        ["python3", str(SCRIPTDIR / "expose.py"), "-d"],
        cwd=str(gallery),
        check=True,
        capture_output=True,
    )
    for item in (gallery / "_site").iterdir():
        dest = python_output / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    shutil.rmtree(gallery / "_site")

    return shell_output, python_output


def _relative_dirs(base):
    return sorted(str(d.relative_to(base)) for d in base.rglob("*") if d.is_dir())


def _relative_files(base):
    return sorted(str(f.relative_to(base)) for f in base.rglob("*") if f.is_file())


def test_parity_directory_structure(parity_outputs):
    shell_dir, python_dir = parity_outputs
    assert _relative_dirs(shell_dir) == _relative_dirs(python_dir)


def test_parity_file_list(parity_outputs):
    shell_dir, python_dir = parity_outputs
    assert _relative_files(shell_dir) == _relative_files(python_dir)


def test_parity_html_title(parity_outputs):
    shell_dir, python_dir = parity_outputs
    for html_path in shell_dir.rglob("*.html"):
        rel = html_path.relative_to(shell_dir)
        py_path = python_dir / rel
        assert py_path.exists(), f"Missing in Python output: {rel}"

        sh_titles = re.findall(r"<title>[^<]*</title>", html_path.read_text())
        py_titles = re.findall(r"<title>[^<]*</title>", py_path.read_text())
        assert sh_titles == py_titles, f"Title mismatch in {rel}"


def test_parity_html_slide_count(parity_outputs):
    shell_dir, python_dir = parity_outputs
    for html_path in shell_dir.rglob("*.html"):
        rel = html_path.relative_to(shell_dir)
        py_path = python_dir / rel

        sh_count = html_path.read_text().count('class="slide"')
        py_count = py_path.read_text().count('class="slide"')
        assert sh_count == py_count, f"Slide count mismatch in {rel}: {sh_count} vs {py_count}"


def test_parity_html_nav_items(parity_outputs):
    shell_dir, python_dir = parity_outputs
    for html_path in shell_dir.rglob("*.html"):
        rel = html_path.relative_to(shell_dir)
        py_path = python_dir / rel

        sh_count = html_path.read_text().count('class="gallery')
        py_count = py_path.read_text().count('class="gallery')
        assert sh_count == py_count, f"Nav item count mismatch in {rel}: {sh_count} vs {py_count}"


def test_parity_html_normalized(parity_outputs):
    """Strictest test: whitespace-normalized HTML must be identical."""
    shell_dir, python_dir = parity_outputs
    for html_path in shell_dir.rglob("*.html"):
        rel = html_path.relative_to(shell_dir)
        py_path = python_dir / rel

        sh_html = " ".join(html_path.read_text().split())
        py_html = " ".join(py_path.read_text().split())
        assert sh_html == py_html, f"Normalized HTML differs in {rel}"


def test_parity_image_files_exist(parity_outputs):
    shell_dir, python_dir = parity_outputs
    sh_jpgs = sorted(str(f.relative_to(shell_dir)) for f in shell_dir.rglob("*.jpg"))
    py_jpgs = sorted(str(f.relative_to(python_dir)) for f in python_dir.rglob("*.jpg"))
    assert sh_jpgs == py_jpgs


def test_parity_image_sizes(parity_outputs):
    """Image file sizes should be within 5% of each other."""
    shell_dir, python_dir = parity_outputs
    for img_path in shell_dir.rglob("*.jpg"):
        rel = img_path.relative_to(shell_dir)
        py_path = python_dir / rel
        assert py_path.exists(), f"Missing image in Python output: {rel}"

        sh_size = img_path.stat().st_size
        py_size = py_path.stat().st_size
        if sh_size == 0:
            continue
        diff_pct = abs(sh_size - py_size) / sh_size
        assert diff_pct <= 0.05, (
            f"Image size differs >5% for {rel}: shell={sh_size}, python={py_size}"
        )
