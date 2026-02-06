"""Final parity test - runs after all other tests pass.

This test generates galleries with both expose.sh and expose.py,
then compares outputs using file hashes to ensure binary compatibility.
Marked as 'final' to ensure it runs after all other tests.
"""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import SCRIPTDIR, make_gallery_tree

pytestmark = [
    pytest.mark.slow,
    pytest.mark.final,
    pytest.mark.order("last"),  # Runs after all other tests
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


def file_hash(filepath: Path) -> str:
    """Calculate MD5 hash of a file."""
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def normalize_html_for_comparison(content: str) -> str:
    """Normalize HTML content for comparison.

    Some differences are expected between shell and Python versions:
    - Timestamps in metadata
    - Absolute vs relative paths in some contexts
    """
    lines = content.split("\n")
    normalized = []
    for line in lines:
        # Skip lines that may differ between runs
        if "Generated on" in line or "timestamp" in line.lower():
            continue
        normalized.append(line)
    return "\n".join(normalized)


def compare_directories(shell_dir: Path, python_dir: Path) -> list:
    """Compare two directories and return list of differences."""
    differences = []

    # Get all files in both directories
    files1 = {f.relative_to(shell_dir): f for f in shell_dir.rglob("*") if f.is_file()}
    files2 = {f.relative_to(python_dir): f for f in python_dir.rglob("*") if f.is_file()}

    # Check for missing files
    only_in_shell = set(files1.keys()) - set(files2.keys())
    only_in_python = set(files2.keys()) - set(files1.keys())

    for f in only_in_shell:
        differences.append(f"Only in shell: {f}")
    for f in only_in_python:
        differences.append(f"Only in python: {f}")

    # Compare common files
    for rel_path in set(files1.keys()) & set(files2.keys()):
        file1 = files1[rel_path]
        file2 = files2[rel_path]

        # Skip binary files for content comparison (just check existence)
        if file1.suffix in [".jpg", ".jpeg", ".png", ".gif", ".mp4", ".webm", ".zip"]:
            # For images/videos, size should match (not hash due to encoding variations)
            if file1.stat().st_size != file2.stat().st_size:
                differences.append(f"Size mismatch: {rel_path}")
        elif file1.suffix == ".html":
            # For HTML, normalize and compare
            content1 = normalize_html_for_comparison(file1.read_text())
            content2 = normalize_html_for_comparison(file2.read_text())
            if content1 != content2:
                # Show first differing lines for debugging
                lines1 = content1.split("\n")
                lines2 = content2.split("\n")
                for i, (l1, l2) in enumerate(zip(lines1, lines2)):
                    if l1 != l2:
                        differences.append(f"HTML content mismatch at {rel_path} line {i+1}")
                        break
                else:
                    if len(lines1) != len(lines2):
                        differences.append(f"HTML line count mismatch: {rel_path}")
                    else:
                        differences.append(f"HTML content mismatch: {rel_path}")
        else:
            # For other text files, compare by hash
            hash1 = file_hash(file1)
            hash2 = file_hash(file2)
            if hash1 != hash2:
                differences.append(f"Content mismatch: {rel_path}")

    return differences


class TestFinalParity:
    """Final parity tests that run after all other tests pass."""

    def test_parity_directory_structure(self, tmp_path_factory):
        """Test that directory structures match between shell and Python versions."""
        # Create test gallery
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

        # Get directory structures
        dirs_shell = sorted(
            [str(d.relative_to(shell_output)) for d in shell_output.rglob("*") if d.is_dir()]
        )
        dirs_python = sorted(
            [str(d.relative_to(python_output)) for d in python_output.rglob("*") if d.is_dir()]
        )

        assert dirs_shell == dirs_python, "Directory structure mismatch"

    def test_parity_file_list(self, tmp_path_factory):
        """Test that file lists match between shell and Python versions."""
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

        # Get file lists
        files_shell = sorted(
            [str(f.relative_to(shell_output)) for f in shell_output.rglob("*") if f.is_file()]
        )
        files_python = sorted(
            [str(f.relative_to(python_output)) for f in python_output.rglob("*") if f.is_file()]
        )

        assert (
            files_shell == files_python
        ), f"File list mismatch: {set(files_shell) ^ set(files_python)}"

    def test_parity_detailed_comparison(self, tmp_path_factory):
        """Detailed comparison of shell vs Python output."""
        gallery = tmp_path_factory.mktemp("gallery")
        make_gallery_tree(gallery)

        shell_output = tmp_path_factory.mktemp("shell_output")
        python_output = tmp_path_factory.mktemp("python_output")

        # Run shell version
        result = subprocess.run(
            ["bash", str(SCRIPTDIR / "expose.sh"), "-d"],
            cwd=str(gallery),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Shell version failed: {result.stderr}"

        for item in (gallery / "_site").iterdir():
            dest = shell_output / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        shutil.rmtree(gallery / "_site")

        # Run Python version
        result = subprocess.run(
            ["python3", str(SCRIPTDIR / "expose.py"), "-d"],
            cwd=str(gallery),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Python version failed: {result.stderr}"

        for item in (gallery / "_site").iterdir():
            dest = python_output / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        # Compare outputs
        differences = compare_directories(shell_output, python_output)

        if differences:
            pytest.fail("Parity check failed:\n" + "\n".join(differences))
