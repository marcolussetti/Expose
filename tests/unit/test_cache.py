"""Tests for the build cache (palettes + output fingerprints) and dry runs."""

import json
from unittest import mock

import pytest
from click.testing import CliRunner

from dorothea.cache import CACHE_NAME, BuildCache, Fingerprint, settings_hash, source_stat
from dorothea.cli import main
from tests.conftest import make_gallery_tree, make_generator, make_test_image


def build(topdir, dry_run=False, **overrides):
    gen = make_generator(topdir, config_overrides=overrides)
    gen.dry_run = dry_run
    gen.scanner.dry_run = dry_run
    gen.run()
    return gen


def site_mtimes(topdir):
    site = topdir / "_site"
    return {p.relative_to(site).as_posix(): p.stat().st_mtime_ns for p in site.rglob("*.jpg")}


class TestBuildCache:
    def test_round_trip(self, tmp_path):
        cache = BuildCache(tmp_path)
        src = tmp_path / "a.jpg"
        cache.put_analysis(src, [1, 2], "k", ["#000000"], 640, 480)
        cache.put_output(tmp_path / "_site" / "a" / "640.jpg", Fingerprint([1, 2], "s"))
        cache.save()

        again = BuildCache(tmp_path)
        assert again.get_analysis(src, [1, 2], "k") == (["#000000"], 640, 480)
        assert again.get_analysis(src, [9, 2], "k") is None  # source changed
        assert again.get_analysis(src, [1, 2], "other") is None  # settings changed
        assert again.get_output(tmp_path / "_site" / "a" / "640.jpg") == Fingerprint([1, 2], "s")

    @pytest.mark.parametrize("content", ["{not json", '{"version": 999}', "[]"])
    def test_unreadable_cache_starts_empty(self, tmp_path, content, capsys):
        (tmp_path / CACHE_NAME).write_text(content)
        cache = BuildCache(tmp_path)
        assert cache.get_output(tmp_path / "x") is None
        assert "Ignoring unreadable build cache" in capsys.readouterr().out

    def test_save_is_skipped_when_unchanged(self, tmp_path):
        BuildCache(tmp_path).save()
        assert not (tmp_path / CACHE_NAME).exists()

    def test_source_stat_of_directory_tracks_frames(self, tmp_path):
        seq = tmp_path / "seq"
        seq.mkdir()
        make_test_image(seq / "0001.jpg")
        before = source_stat(seq)
        make_test_image(seq / "0002.jpg")
        assert source_stat(seq) != before

    def test_settings_hash_is_order_independent(self):
        assert settings_hash(a=1, b=[2, 3]) == settings_hash(b=[2, 3], a=1)
        assert settings_hash(a=1) != settings_hash(a=2)


class TestFingerprintRebuilds:
    def test_second_build_encodes_nothing(self, tmp_gallery):
        build(tmp_gallery)
        before = site_mtimes(tmp_gallery)
        build(tmp_gallery)
        assert site_mtimes(tmp_gallery) == before
        assert (tmp_gallery / CACHE_NAME).exists()

    def test_changed_quality_rebuilds_images(self, tmp_gallery):
        build(tmp_gallery)
        before = site_mtimes(tmp_gallery)
        build(tmp_gallery, jpeg_quality=80)
        after = site_mtimes(tmp_gallery)
        assert all(after[p] != before[p] for p in before)

    def test_new_image_options_rebuild_only_that_item(self, tmp_gallery):
        build(tmp_gallery)
        before = site_mtimes(tmp_gallery)
        (tmp_gallery / "02 Urban" / "01 city.txt").write_text(
            "image-options: -negate\n---\nA city\n"
        )
        build(tmp_gallery)
        after = site_mtimes(tmp_gallery)
        changed = {str(p) for p in before if after[p] != before[p]}
        assert changed == {"urban/city/1024.jpg"}

    def test_site_without_cache_is_adopted(self, tmp_gallery):
        """An existing, up-to-date _site with no cache (e.g. from expose.sh) isn't re-encoded."""
        build(tmp_gallery)
        (tmp_gallery / CACHE_NAME).unlink()
        before = site_mtimes(tmp_gallery)
        build(tmp_gallery)
        assert site_mtimes(tmp_gallery) == before
        assert json.loads((tmp_gallery / CACHE_NAME).read_text())["outputs"]


class TestAnalysisCache:
    def test_cached_palettes_skip_extraction(self, tmp_gallery):
        build(tmp_gallery)
        gen = make_generator(tmp_gallery)
        with mock.patch.object(
            gen.scanner.color_extractor, "extract_palette", side_effect=AssertionError
        ):
            gen.scan_directories()
            gen.read_files()
        assert len(gen.gallery_colors) == 3
        gen.cleanup()

    def test_edited_photo_is_reanalysed(self, tmp_gallery):
        build(tmp_gallery)
        make_test_image(tmp_gallery / "02 Urban" / "01 city.jpg", 640, 480, "green")
        gen = make_generator(tmp_gallery)
        real = gen.scanner.color_extractor.extract_palette
        with mock.patch.object(
            gen.scanner.color_extractor, "extract_palette", side_effect=real
        ) as spy:
            gen.scan_directories()
            gen.read_files()
        assert spy.call_count == 1
        gen.cleanup()


class TestDryRun:
    def test_writes_nothing(self, tmp_gallery):
        gen = build(tmp_gallery, dry_run=True)
        assert not (tmp_gallery / "_site").exists()
        assert not (tmp_gallery / CACHE_NAME).exists()
        assert gen.planned_pages == 4
        assert sorted(p for p, _ in gen.planned) == [
            "nature/mountains/peak/1024.jpg",
            "nature/oceans/wave/1024.jpg",
            "urban/city/1024.jpg",
        ]
        assert {reason for _, reason in gen.planned} == {"new"}

    def test_reports_what_a_real_run_would_do(self, tmp_gallery):
        build(tmp_gallery)
        make_test_image(tmp_gallery / "02 Urban" / "01 city.jpg", 640, 480, "green")
        gen = build(tmp_gallery, dry_run=True, jpeg_quality=80)
        reasons = dict(gen.planned)
        assert reasons["urban/city/1024.jpg"] == "source changed"
        assert reasons["nature/oceans/wave/1024.jpg"] == "settings changed"

    def test_cli_summary(self, tmp_path, monkeypatch):
        make_gallery_tree(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(main, ["-n", "-d"])
        assert result.exit_code == 0, result.output
        out = result.stdout
        assert "Would write 4 HTML pages; would encode 3 files (3 new)" in out
        assert "urban/city/1024.jpg  [new]" in out
        assert not (tmp_path / "_site").exists()


@pytest.mark.slow
def test_video_plan_build_and_rebuild(tmp_path):
    """Videos: the dry run lists every output, a real build makes them, a rebuild does nothing."""
    import subprocess

    from dorothea.media.ffmpeg import ffmpeg_exe

    gallery = tmp_path / "gallery"
    gallery.mkdir()
    subprocess.run(
        [ffmpeg_exe(), "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc=size=640x360:rate=12", "-t", "1", "-pix_fmt", "yuv420p",
         str(gallery / "clip.mp4")],
        check=True,
    )  # fmt: skip
    settings = {
        "resolution": [640, 320],
        "bitrate": [1, 1],
        "video_formats": ["h264"],
        "h264_encodespeed": "ultrafast",
    }

    def run(dry_run):
        gen = make_generator(tmp_path, config_overrides=settings, draft=False)
        gen.dry_run = gen.scanner.dry_run = dry_run
        gen.run()
        return sorted(gen.planned)

    expected = ["gallery/clip/320-h264.mp4", "gallery/clip/320.jpg",
                "gallery/clip/640-h264.mp4", "gallery/clip/640.jpg"]  # fmt: skip
    assert [p for p, _ in run(dry_run=True)] == expected
    run(dry_run=False)
    for rel in expected:
        assert (tmp_path / "_site" / rel).stat().st_size > 0
    assert run(dry_run=True) == []

    settings["bitrate"] = [2, 1]
    assert run(dry_run=True) == [("gallery/clip/640-h264.mp4", "settings changed")]
