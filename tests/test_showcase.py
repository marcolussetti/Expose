"""Full build of tests/data/showcase, the multi-gallery site used to check theme layouts.

Regenerate it with ``scripts/make_showcase_gallery.py``. Its ``_config.yml`` turns on the feed
and whole-gallery downloads, so the pages carry every optional link.
"""

import shutil
import zipfile

import pytest
from click.testing import CliRunner

from dorothea.cli import main
from tests.conftest import DATADIR

SHOWCASE = DATADIR / "showcase"
PAGES = ["travel/iceland", "travel/norway", "portraits"]


@pytest.fixture(scope="module", params=["photoessay", "medium"])
def site(request, tmp_path_factory):
    """The showcase built (not draft) with one of Dorothea's themes."""
    topdir = tmp_path_factory.mktemp(request.param) / "showcase"
    shutil.copytree(SHOWCASE, topdir)
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(topdir)
        result = CliRunner().invoke(main, ["-s", f"theme_dir={request.param}"])
    assert result.exit_code == 0, result.output
    return topdir / "_site"


@pytest.mark.slow
class TestShowcase:
    def test_every_gallery_has_a_page(self, site):
        assert (site / "index.html").is_file()
        for page in PAGES:
            assert (site / page / "index.html").is_file()

    def test_photos_encoded_at_each_resolution(self, site):
        # 1600px originals: every resolution in the config is built
        for res in (1600, 1024, 640):
            assert (site / "travel" / "iceland" / "01" / f"{res}.jpg").is_file()

    def test_pages_link_feeds_and_album_zips(self, site):
        html = (site / "travel" / "iceland" / "index.html").read_text(encoding="utf-8")
        assert "https://example.com/photos/feed.xml" in html
        assert 'href="iceland.zip"' in html
        assert (site / "feed.xml").is_file()

    def test_album_zips_hold_the_originals(self, site):
        with zipfile.ZipFile(site / "travel" / "iceland" / "iceland.zip") as zf:
            assert zf.namelist() == ["01.jpg", "02.jpg", "03.jpg", "04.jpg", "readme.txt"]
