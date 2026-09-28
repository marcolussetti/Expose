"""Generate tests/data/showcase: a small multi-gallery site for checking theme layouts.

Landscape and portrait photos (gradients, so resized images look like photos rather than flat
colour), short and long captions, a title caption on each gallery's first photo, and nested
galleries. Its _config.yml turns on the feed and whole-gallery downloads, so theme headers
show every optional link.

    uv run python scripts/make_showcase_gallery.py tests/data/showcase
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

LOREM = (
    "We drove the ring road for two weeks, stopping wherever the light was good. "
    "Most mornings started in fog and ended in a wind that made standing still a chore, "
    "but every so often the clouds broke and the whole valley lit up at once."
)

Colour = tuple[int, int, int]

# gallery folder -> photos as ((width, height), top colour, bottom colour, caption)
GALLERIES: dict[str, list[tuple[tuple[int, int], Colour, Colour, str]]] = {
    "01 Travel/01 Iceland": [
        ((1600, 1067), (30, 60, 120), (200, 120, 60), "# Iceland\n\nTwo weeks on the ring road."),
        ((1067, 1600), (20, 90, 60), (230, 230, 210), LOREM),
        ((1600, 1067), (90, 20, 60), (240, 180, 90), "A **short** caption."),
        ((1600, 800), (10, 10, 40), (80, 160, 200), LOREM + " " + LOREM),
    ],
    "01 Travel/02 Norway": [
        ((1600, 1067), (60, 60, 60), (220, 220, 240), "# Norway"),
        ((1600, 1067), (20, 40, 20), (120, 200, 120), LOREM),
    ],
    "02 Portraits": [
        ((1067, 1600), (120, 80, 60), (240, 210, 190), "# Portraits"),
        ((1067, 1600), (40, 40, 80), (200, 200, 250), "Studio, natural light."),
    ],
}

CONFIG = """\
site_title: Showcase
site_url: https://example.com/photos/
download_album: true
resolution: [1600, 1024, 640]
"""


def photo(path: Path, size: tuple[int, int], top: Colour, bottom: Colour) -> None:
    """A vertical gradient with a pale 'sun', saved as a JPEG."""
    w, h = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        colour = tuple(int(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
        draw.line([(0, y), (w, y)], fill=colour)
    draw.ellipse([w * 0.6, h * 0.2, w * 0.75, h * 0.2 + w * 0.15], fill=(250, 240, 200))
    img.save(path, quality=80)


def main(root: Path) -> None:
    for name, photos in GALLERIES.items():
        folder = root / name
        folder.mkdir(parents=True, exist_ok=True)
        for i, (size, top, bottom, caption) in enumerate(photos, 1):
            photo(folder / f"{i:02d}.jpg", size, top, bottom)
            (folder / f"{i:02d}.txt").write_text(caption + "\n", encoding="utf-8")
    (root / "_config.yml").write_text(CONFIG, encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
