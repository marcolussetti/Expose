"""The ``sort`` setting / ``--sort`` (#10)."""

import os

import pytest
from click.testing import CliRunner

from dorothea.cli import main
from dorothea.config import DEFAULT_CONFIG, EXPOSE_DEFAULTS, Config, ConfigError
from dorothea.sorting import SORT_MODES, natural_key, sort_items
from tests.conftest import make_generator, make_test_image
from tests.unit.test_collisions import photo


def order(topdir, mode=None):
    """Scan ``topdir`` and return (gallery names in nav order, photo file names in order)."""
    gen = make_generator(topdir, config_overrides={"sort": mode} if mode else None)
    gen.scan_directories()
    gen.read_files()
    gen.cleanup()
    return [p.name for p in gen.paths[1:]], [f.name for f in gen.gallery_files]


class TestNaturalKey:
    def test_numbers_compare_numerically(self):
        names = ["img10.jpg", "img2.jpg", "img1.jpg", "IMG3.jpg"]
        assert sorted(names, key=natural_key) == ["img1.jpg", "img2.jpg", "IMG3.jpg", "img10.jpg"]

    def test_leading_numbers(self):
        names = ["10 Departure", "1 Arrival", "2 Hike"]
        assert sorted(names, key=natural_key) == ["1 Arrival", "2 Hike", "10 Departure"]


class TestSortItems:
    items = ["a1", "a10", "a2"]  # already in plain name order

    def test_name_is_unchanged(self):
        assert sort_items(self.items, "name", str, lambda _: 0.0) == self.items

    @pytest.mark.parametrize(
        "mode,expected",
        [
            ("name-desc", ["a2", "a10", "a1"]),
            ("natural", ["a1", "a2", "a10"]),
            ("natural-desc", ["a10", "a2", "a1"]),
        ],
    )
    def test_modes(self, mode, expected):
        assert sort_items(self.items, mode, str, lambda _: 0.0) == expected

    def test_capture_uses_taken_at(self):
        times = {"a1": 30.0, "a10": 10.0, "a2": 20.0}
        assert sort_items(self.items, "capture", str, times.get) == ["a10", "a2", "a1"]
        assert sort_items(self.items, "capture-desc", str, times.get) == ["a1", "a2", "a10"]


class TestPhotoOrder:
    def _gallery(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        for stem, taken in [("1 a", "2020:03:01 00:00:00"), ("10 b", "2020:01:01 00:00:00"),
                            ("2 c", "2020:02:01 00:00:00")]:  # fmt: skip
            photo(g / f"{stem}.jpg", "red", taken=taken)
        return g

    def test_default_is_natural_order(self, tmp_path):
        self._gallery(tmp_path)
        assert order(tmp_path)[1] == ["1 a.jpg", "2 c.jpg", "10 b.jpg"]

    def test_name_order(self, tmp_path):
        """expose.sh's order (the --legacy default)."""
        self._gallery(tmp_path)
        assert order(tmp_path, "name")[1] == ["1 a.jpg", "10 b.jpg", "2 c.jpg"]

    @pytest.mark.parametrize(
        "mode,expected",
        [
            ("natural", ["1 a.jpg", "2 c.jpg", "10 b.jpg"]),
            ("natural-desc", ["10 b.jpg", "2 c.jpg", "1 a.jpg"]),
            ("name-desc", ["2 c.jpg", "10 b.jpg", "1 a.jpg"]),
            ("capture", ["10 b.jpg", "2 c.jpg", "1 a.jpg"]),
            ("capture-desc", ["1 a.jpg", "2 c.jpg", "10 b.jpg"]),
        ],
    )
    def test_modes(self, tmp_path, mode, expected):
        self._gallery(tmp_path)
        assert order(tmp_path, mode)[1] == expected

    def test_capture_falls_back_to_file_time(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        make_test_image(g / "a.jpg")
        make_test_image(g / "b.jpg")
        os.utime(g / "a.jpg", (2_000_000_000, 2_000_000_000))
        os.utime(g / "b.jpg", (1_000_000_000, 1_000_000_000))
        assert order(tmp_path, "capture")[1] == ["b.jpg", "a.jpg"]

    def test_metadata_txt_overrides_for_that_gallery(self, tmp_path, capsys):
        g = self._gallery(tmp_path)
        (g / "metadata.txt").write_text("sort: natural-desc\n")
        other = tmp_path / "other"
        other.mkdir()
        make_test_image(other / "10.jpg")
        make_test_image(other / "9.jpg")
        galleries, photos = order(tmp_path, "name")
        assert photos == ["10 b.jpg", "2 c.jpg", "1 a.jpg", "10.jpg", "9.jpg"]  # other: name

    def test_invalid_override_is_ignored(self, tmp_path, capsys):
        g = self._gallery(tmp_path)
        (g / "metadata.txt").write_text("sort: sideways\n")
        assert order(tmp_path, "name")[1] == ["1 a.jpg", "10 b.jpg", "2 c.jpg"]
        assert "Ignoring 'sort: sideways'" in capsys.readouterr().out


class TestGalleryOrder:
    def _trip(self, tmp_path):
        """Galleries named out of chronological order, with nested sections."""
        for folder, taken in [
            ("1 Reykjavik", "2022:09:25 10:00:00"),
            ("10 Vik", "2022:09:20 10:00:00"),
            ("2 Akureyri", "2022:09:22 10:00:00"),
        ]:
            (tmp_path / "Iceland" / folder).mkdir(parents=True)
            photo(tmp_path / "Iceland" / folder / "shot.jpg", "red", taken=taken)
        (tmp_path / "Japan" / "Tokyo").mkdir(parents=True)
        photo(tmp_path / "Japan" / "Tokyo" / "shot.jpg", "blue", taken="2021:04:01 10:00:00")

    def test_name_is_path_order(self, tmp_path):
        self._trip(tmp_path)
        assert order(tmp_path, "name")[0] == [
            "Iceland",
            "1 Reykjavik",
            "10 Vik",
            "2 Akureyri",
            "Japan",
            "Tokyo",
        ]

    def test_natural(self, tmp_path):
        self._trip(tmp_path)
        assert order(tmp_path, "natural")[0] == [
            "Iceland", "1 Reykjavik", "2 Akureyri", "10 Vik", "Japan", "Tokyo"
        ]  # fmt: skip

    def test_capture_follows_the_trip(self, tmp_path):
        """Sections sort by their earliest photo (Japan 2021 before Iceland 2022), then galleries."""
        self._trip(tmp_path)
        assert order(tmp_path, "capture")[0] == [
            "Japan", "Tokyo", "Iceland", "10 Vik", "2 Akureyri", "1 Reykjavik"
        ]  # fmt: skip

    def test_capture_desc(self, tmp_path):
        self._trip(tmp_path)
        assert order(tmp_path, "capture-desc")[0] == [
            "Iceland", "1 Reykjavik", "2 Akureyri", "10 Vik", "Japan", "Tokyo"
        ]  # fmt: skip

    def test_urls_follow_the_new_order(self, tmp_path):
        """Reordering sections must not mix up nested URLs."""
        self._trip(tmp_path)
        gen = make_generator(tmp_path, config_overrides={"sort": "capture"})
        gen.run()
        site = tmp_path / "_site"
        for rel in ["japan/tokyo", "iceland/vik", "iceland/akureyri", "iceland/reykjavik"]:
            assert (site / rel / "shot" / "1024.jpg").exists(), rel


class TestSortSetting:
    def test_default(self):
        assert DEFAULT_CONFIG["sort"] == "natural"
        assert EXPOSE_DEFAULTS["sort"] == "name"  # --legacy

    @pytest.mark.parametrize("mode", SORT_MODES)
    def test_valid(self, mode, tmp_path):
        Config({**DEFAULT_CONFIG, "sort": mode}).validate(tmp_path)

    def test_invalid(self, tmp_path):
        with pytest.raises(ConfigError, match="sort must be one of"):
            Config({**DEFAULT_CONFIG, "sort": "random"}).validate(tmp_path)

    def test_cli_flag(self, tmp_path, monkeypatch):
        g = tmp_path / "g"
        g.mkdir()
        make_test_image(g / "10.jpg")
        make_test_image(g / "9.jpg")
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(main, ["-n", "-d", "--sort", "natural"])
        assert result.exit_code == 0, result.output
        assert result.stdout.index("g/9/1024.jpg") < result.stdout.index("g/10/1024.jpg")

    def test_cli_rejects_unknown_mode(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(main, ["--sort", "random"])
        assert result.exit_code == 2
        assert "sort must be one of" in result.stderr
