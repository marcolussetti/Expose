"""Parity tests — compare expose.sh vs expose.py output.

These tests run both generators on the same gallery and verify identical output.
Marked as slow since they invoke two full pipeline runs.
"""

import re
import shutil
import subprocess

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
        assert (
            diff_pct <= 0.05
        ), f"Image size differs >5% for {rel}: shell={sh_size}, python={py_size}"


@pytest.fixture(scope="session")
def real_gallery_parity_outputs(tmp_path_factory):
    """Run both expose.sh and expose.py on the REAL test_run gallery.

    This uses actual JPEG images instead of synthetic test images,
    providing a more realistic parity test.
    """
    test_run = SCRIPTDIR / "test_run"

    # Skip if test_run doesn't exist or doesn't have source images
    if not test_run.exists():
        pytest.skip("test_run directory not found")

    # Check for actual source images (not just _site)
    source_images = list((test_run).rglob("*.jpg"))
    source_images = [img for img in source_images if "_site" not in str(img)]
    if not source_images:
        pytest.skip("No source images found in test_run")

    # Create a temporary copy of test_run (so we don't modify the original)
    gallery = tmp_path_factory.mktemp("real_gallery")
    for item in test_run.iterdir():
        if item.name == "_site":
            continue  # Don't copy existing _site
        if item.is_dir():
            shutil.copytree(item, gallery / item.name)
        else:
            shutil.copy2(item, gallery / item.name)

    shell_output = tmp_path_factory.mktemp("real_shell_output")
    python_output = tmp_path_factory.mktemp("real_python_output")

    # Run shell version
    result = subprocess.run(
        ["bash", str(SCRIPTDIR / "expose.sh"), "-d"],
        cwd=str(gallery),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"Shell version failed on real gallery: {result.stderr}")

    # Copy _site to shell_output
    site_dir = gallery / "_site"
    if not site_dir.exists():
        pytest.fail("Shell version did not create _site directory")

    for item in site_dir.iterdir():
        dest = shell_output / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    shutil.rmtree(site_dir)

    # Run Python version
    result = subprocess.run(
        ["python3", str(SCRIPTDIR / "expose.py"), "-d"],
        cwd=str(gallery),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"Python version failed on real gallery: {result.stderr}")

    if not site_dir.exists():
        pytest.fail("Python version did not create _site directory")

    for item in site_dir.iterdir():
        dest = python_output / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    return shell_output, python_output


class TestRealGalleryParity:
    """Parity tests using the real test_run gallery with actual JPEG images."""

    def test_real_gallery_directory_structure(self, real_gallery_parity_outputs):
        """Directory structure must match exactly."""
        shell_dir, python_dir = real_gallery_parity_outputs
        assert _relative_dirs(shell_dir) == _relative_dirs(python_dir)

    def test_real_gallery_file_list(self, real_gallery_parity_outputs):
        """File lists must match exactly."""
        shell_dir, python_dir = real_gallery_parity_outputs
        shell_files = _relative_files(shell_dir)
        python_files = _relative_files(python_dir)

        if shell_files != python_files:
            only_shell = set(shell_files) - set(python_files)
            only_python = set(python_files) - set(shell_files)
            msg = []
            if only_shell:
                msg.append(f"Only in shell: {only_shell}")
            if only_python:
                msg.append(f"Only in python: {only_python}")
            pytest.fail("\n".join(msg))

    def test_real_gallery_html_content(self, real_gallery_parity_outputs):
        """HTML content must match (whitespace-normalized)."""
        shell_dir, python_dir = real_gallery_parity_outputs

        for html_path in shell_dir.rglob("*.html"):
            rel = html_path.relative_to(shell_dir)
            py_path = python_dir / rel
            assert py_path.exists(), f"Missing HTML in Python output: {rel}"

            # Normalize whitespace for comparison
            sh_html = " ".join(html_path.read_text().split())
            py_html = " ".join(py_path.read_text().split())

            assert sh_html == py_html, f"HTML content differs in {rel}"

    def test_real_gallery_image_sizes(self, real_gallery_parity_outputs):
        """Image sizes should be within 5% (JPEG compression can vary slightly)."""
        shell_dir, python_dir = real_gallery_parity_outputs

        for img_path in shell_dir.rglob("*.jpg"):
            rel = img_path.relative_to(shell_dir)
            py_path = python_dir / rel
            assert py_path.exists(), f"Missing image in Python output: {rel}"

            sh_size = img_path.stat().st_size
            py_size = py_path.stat().st_size

            if sh_size == 0:
                continue

            diff_pct = abs(sh_size - py_size) / sh_size
            assert (
                diff_pct <= 0.05
            ), f"Image size differs >5% for {rel}: shell={sh_size}, python={py_size}, diff={diff_pct*100:.1f}%"

    def test_real_gallery_css_js_exact(self, real_gallery_parity_outputs):
        """CSS and JS files must match exactly (byte-for-byte)."""
        shell_dir, python_dir = real_gallery_parity_outputs

        for file_path in shell_dir.rglob("*"):
            if not file_path.is_file():
                continue

            if file_path.suffix not in [".css", ".js"]:
                continue

            rel = file_path.relative_to(shell_dir)
            py_path = python_dir / rel
            assert py_path.exists(), f"Missing file in Python output: {rel}"

            sh_content = file_path.read_bytes()
            py_content = py_path.read_bytes()

            assert sh_content == py_content, f"File content differs: {rel}"
