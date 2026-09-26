"""Tests for parallel encoding, incremental rebuilds, image-options and scan pruning."""

import hashlib
import os
import shutil
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image

from tests.conftest import DATADIR, make_gallery_tree, make_generator, make_test_image


def build(topdir, **overrides):
    """Run the full pipeline (draft) and return the generator's scan order."""
    gen = make_generator(topdir, config_overrides=overrides)
    gen.scan_directories()
    gen.read_files()
    gen.build_html()
    gen.encode_media()
    gen.copy_resources()
    order = [str(p) for p in gen.gallery_files]
    gen.cleanup()
    return order


def site_digest(topdir):
    """Map of relative path -> md5 for every file in _site."""
    site = Path(topdir) / "_site"
    return {
        str(f.relative_to(site)): hashlib.md5(f.read_bytes()).hexdigest()
        for f in sorted(site.rglob("*"))
        if f.is_file()
    }


def copy_test_run(dest):
    shutil.copytree(DATADIR / "test_run", dest, ignore=shutil.ignore_patterns("_site"))
    return dest


class TestParallelEncoding:
    def test_parallel_output_identical_to_serial(self, tmp_path):
        """jobs=1 and jobs=4 produce byte-identical sites on the real test gallery."""
        serial = copy_test_run(tmp_path / "serial")
        parallel = copy_test_run(tmp_path / "parallel")

        order_serial = build(serial, jobs=1)
        order_parallel = build(parallel, jobs=4)

        assert [Path(p).relative_to(serial) for p in order_serial] == [
            Path(p).relative_to(parallel) for p in order_parallel
        ]
        assert site_digest(serial) == site_digest(parallel)
        assert site_digest(serial)  # sanity: something was generated

    def test_no_partial_files_left(self, tmp_gallery):
        build(tmp_gallery, jobs=4)
        assert list((tmp_gallery / "_site").rglob("*.part.*")) == []

    def test_corrupt_image_does_not_abort_build(self, tmp_path, capsys):
        gallery = tmp_path / "gallery"
        gallery.mkdir()
        make_test_image(gallery / "01 good.jpg", 1200, 900, "green")
        (gallery / "02 broken.jpg").write_bytes(b"not a jpeg")
        make_test_image(gallery / "03 also good.jpg", 1200, 900, "red")

        build(tmp_path, jobs=2)

        site = tmp_path / "_site" / "gallery"
        assert (site / "good" / "1024.jpg").exists()
        assert (site / "also-good" / "1024.jpg").exists()
        assert not (site / "broken" / "1024.jpg").exists()
        assert "Error encoding" in capsys.readouterr().out


class TestIncrementalRebuild:
    def test_unchanged_source_is_skipped(self, tmp_gallery):
        build(tmp_gallery)
        out = tmp_gallery / "_site" / "urban" / "city" / "1024.jpg"
        before = out.stat().st_mtime_ns
        build(tmp_gallery)
        assert out.stat().st_mtime_ns == before

    def test_newer_source_is_reencoded(self, tmp_gallery):
        build(tmp_gallery)
        out = tmp_gallery / "_site" / "urban" / "city" / "1024.jpg"
        other = tmp_gallery / "_site" / "nature" / "oceans" / "wave" / "1024.jpg"
        os.utime(out, (1, 1))  # pretend the output predates the source
        other_before = other.stat().st_mtime_ns

        build(tmp_gallery)

        assert out.stat().st_mtime > 1
        assert other.stat().st_mtime_ns == other_before


@pytest.mark.skipif(shutil.which("convert") is None, reason="ImageMagick not installed")
class TestImageOptions:
    def _gallery_with_options(self, tmp_path, options):
        gallery = tmp_path / "gallery"
        gallery.mkdir()
        make_test_image(gallery / "photo.jpg", 1200, 900, "blue")
        (gallery / "photo.txt").write_text(f"image-options: {options}\n---\nA caption\n")
        return tmp_path / "_site" / "gallery" / "photo" / "1024.jpg"

    def test_image_options_applied_via_imagemagick(self, tmp_path):
        out = self._gallery_with_options(tmp_path, "-negate")
        build(tmp_path)
        with Image.open(out) as img:
            r, g, b = img.convert("RGB").getpixel((10, 10))
        # blue negated is yellow
        assert r > 200 and g > 200 and b < 60

    def test_image_options_warn_without_imagemagick(self, tmp_path, capsys):
        from pyexpose.media.image import ImageProcessor

        out = self._gallery_with_options(tmp_path, "-negate")
        with (
            mock.patch("pyexpose.media.image.shutil.which", return_value=None),
            mock.patch.object(ImageProcessor, "_warned_no_convert", False),
        ):
            build(tmp_path)
        with Image.open(out) as img:
            r, g, b = img.convert("RGB").getpixel((10, 10))
        assert b > 200  # still blue: options ignored
        assert "image-options ignored" in capsys.readouterr().out


class TestScanPruning:
    def _reference_order(self, topdir):
        """The pre-os.walk implementation: rglob everything, filter afterwards."""
        dirs = sorted(d for d in topdir.rglob("*") if d.is_dir())
        keep = []
        for node in dirs:
            parts = node.relative_to(topdir).parts
            if any(p.startswith(("_", ".")) for p in parts):
                continue
            keep.append(node)
        return keep

    def test_scan_order_matches_rglob(self, tmp_path):
        make_gallery_tree(tmp_path)
        (tmp_path / ".hidden" / "inner").mkdir(parents=True)
        (tmp_path / "_drafts" / "x").mkdir(parents=True)
        (tmp_path / "_site" / "old" / "deep").mkdir(parents=True)
        make_test_image(tmp_path / ".hidden" / "inner" / "a.jpg")
        make_test_image(tmp_path / "_drafts" / "x" / "a.jpg")

        gen = make_generator(tmp_path)
        with mock.patch("pathlib.Path.rglob", side_effect=AssertionError("rglob used")):
            gen.scan_directories()
        expected = [tmp_path] + [d for d in self._reference_order(tmp_path) if any(d.iterdir())]
        assert gen.paths == expected
        gen.cleanup()
