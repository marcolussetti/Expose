"""Non-Latin names (#18) and hidden files/folders inside galleries (#7)."""

import unicodedata
from urllib.parse import unquote

import pytest

from dorothea.utils import href, site_path, slug_or_fallback, url_safe
from tests.conftest import make_generator, make_test_image


def build(topdir, **overrides):
    gen = make_generator(topdir, config_overrides=overrides)
    gen.run()
    return gen


class TestSlugs:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("My Photos", "my-photos"),
            ("01 Nature & Wildlife", "01-nature--wildlife"),
            ("snake_case name", "snakecase-name"),  # underscores stripped, like expose.sh
            ("Москва", "москва"),
            ("北京", "北京"),
            ("Café Zürich", "café-zürich"),
            ("Straße", "straße"),
            ("🌅 sunrise", "-sunrise"),
        ],
    )
    def test_url_safe(self, name, expected):
        assert url_safe(name) == expected

    def test_decomposed_names_match_composed(self):
        """macOS stores names as NFD; the URL must be the same as on other systems."""
        name = "Café Zürich"
        assert url_safe(unicodedata.normalize("NFD", name)) == url_safe(name)

    @pytest.mark.parametrize("name", ["🌅", "!!!", "★☆"])
    def test_empty_slug_falls_back_stably(self, name):
        slug = slug_or_fallback(name, "gallery")
        assert slug.startswith("gallery-") and len(slug) == len("gallery-") + 8
        assert slug_or_fallback(name, "gallery") == slug  # deterministic

    def test_ascii_hrefs_unchanged(self):
        assert href("nature/mountains") == "nature/mountains"
        assert href("москва") == "%D0%BC%D0%BE%D1%81%D0%BA%D0%B2%D0%B0"

    def test_site_path_refuses_to_escape(self, tmp_path):
        site = tmp_path / "_site"
        site.mkdir()
        assert site_path(site, "a/b") == (site / "a" / "b").resolve()
        for bad in ("/", "/etc", "../outside", "a/../../outside"):
            with pytest.raises(ValueError, match="outside"):
                site_path(site, bad)


class TestNonLatinGalleries:
    def test_build_with_non_latin_names(self, tmp_path):
        """Used to crash writing to / (empty gallery URLs); now every gallery gets its own URL."""
        for folder, photo in [
            ("01 Москва", "Красная площадь"),
            ("02 北京", "故宫"),
            ("03 Café Zürich", "Straße"),
            ("04 🌅", "🌅"),
        ]:
            (tmp_path / folder).mkdir()
            make_test_image(tmp_path / folder / f"{photo}.jpg", 1200, 900, "red")

        build(tmp_path)

        site = tmp_path / "_site"
        for rel in ["москва/красная-площадь", "北京/故宫", "café-zürich/straße"]:
            assert (site / rel / "1024.jpg").exists(), rel
        emoji_gallery = slug_or_fallback("🌅", "gallery")
        assert (site / emoji_gallery / slug_or_fallback("🌅", "item") / "1024.jpg").exists()

        index = (site / "index.html").read_text(encoding="utf-8")
        assert 'href="./%D0%BC%D0%BE%D1%81%D0%BA%D0%B2%D0%B0"' in index
        assert "<span>Москва</span>" in index  # display names stay readable
        assert 'href="./"' not in index

    def test_encoded_links_resolve_to_real_folders(self, tmp_path):
        (tmp_path / "Café").mkdir()
        make_test_image(tmp_path / "Café" / "Été.jpg", 1200, 900, "blue")
        build(tmp_path)
        page = (tmp_path / "_site" / "café" / "index.html").read_text(encoding="utf-8")
        url = page.split('data-url="')[1].split('"')[0]
        assert url == "%C3%A9t%C3%A9"
        assert (tmp_path / "_site" / "café" / unquote(url) / "1024.jpg").exists()


class TestHiddenFiles:
    def _gallery(self, tmp_path):
        g = tmp_path / "g"
        g.mkdir()
        make_test_image(g / "photo.jpg", 1200, 900, "red")
        return g

    def test_hidden_subfolder_keeps_gallery_photos(self, tmp_path):
        g = self._gallery(tmp_path)
        for hidden in (".thumbs", ".git"):
            (g / hidden).mkdir()
            make_test_image(g / hidden / "x.jpg")
        build(tmp_path)
        assert (tmp_path / "_site" / "g" / "photo" / "1024.jpg").exists()
        assert not (tmp_path / "_site" / "g" / "thumbs").exists()

    def test_dotfiles_are_not_published(self, tmp_path, capsys):
        g = self._gallery(tmp_path)
        make_test_image(g / ".hidden.jpg")
        (g / "._photo.jpg").write_bytes(b"\x00\x05\x16\x07AppleDouble junk")
        (g / ".DS_Store").write_bytes(b"junk")
        gen = build(tmp_path)
        assert [p.name for p in gen.gallery_files] == ["photo.jpg"]
        assert "Error encoding" not in capsys.readouterr().out
        assert sorted(p.name for p in (tmp_path / "_site" / "g").iterdir()) == [
            "index.html",
            "photo",
        ]

    def test_folder_with_only_hidden_files_is_not_a_gallery(self, tmp_path):
        self._gallery(tmp_path)
        (tmp_path / "emptied").mkdir()
        (tmp_path / "emptied" / ".DS_Store").write_bytes(b"junk")
        gen = build(tmp_path)
        assert all(p.name != "emptied" for p in gen.paths)

    def test_sequence_ignores_hidden_frames(self, tmp_path):
        seq = tmp_path / "g" / "walk-imagesequence"
        seq.mkdir(parents=True)
        make_test_image(seq / "0001.jpg", 320, 240, "red")
        make_test_image(seq / "0002.jpg", 320, 240, "blue")
        (seq / "._0001.jpg").write_bytes(b"AppleDouble junk")
        gen = make_generator(tmp_path)
        gen.config["h264_encodespeed"] = "ultrafast"
        frames = []
        real = gen._make_encoder()._compile_sequence

        def spy(seq_dir, scratch=None):
            video = real(seq_dir, scratch)
            frames.extend(sorted(p.name for p in (scratch or gen.scratchdir).iterdir()))
            return video

        video = spy(seq)
        assert video is not None
        assert [f for f in frames if f[0].isdigit()] == ["0000.jpg", "0001.jpg"]
        gen.cleanup()
