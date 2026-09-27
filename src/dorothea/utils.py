"""Utility functions for Dorothea.

Pure utility functions with no external dependencies.
"""

import hashlib
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote


def url_safe(name: str) -> str:
    """Convert name to URL-safe format.

    Keeps letters and digits from any script, drops everything else except spaces, turns
    spaces into hyphens and lowercases. For ASCII names this is exactly expose.sh's
    ``sed 's/[^ a-zA-Z0-9]//g;s/ /-/g' | tr '[:upper:]' '[:lower:]'`` (parity); expose.sh also
    drops non-ASCII letters, which leaves names like "Москва" empty.

    Args:
        name: Input name.

    Returns:
        URL-safe name (may be empty for names with no letters or digits; see ``slug_or_fallback``).

    Examples:
        >>> url_safe("My Photos")
        'my-photos'
        >>> url_safe("01 Nature & Wildlife")
        '01-nature--wildlife'
        >>> url_safe("Café Zürich")
        'café-zürich'
    """
    # NFC first: macOS stores names decomposed ("e" + combining accent), and the accent alone
    # isn't a word character, so "café" would otherwise become "cafe" only on macOS.
    # \w is Unicode-aware; underscores are word characters but expose.sh strips them.
    result = re.sub(r"[^\w ]|_", "", unicodedata.normalize("NFC", name))
    return result.replace(" ", "-").lower()


def slug_or_fallback(name: str, kind: str) -> str:
    """``url_safe(name)``, or a stable ``<kind>-<hash>`` name when nothing is left.

    Names made only of symbols or emoji would otherwise produce an empty URL, which puts output
    in the wrong place. The hash of the original name keeps the fallback stable across builds.
    """
    return url_safe(name) or f"{kind}-{hashlib.sha1(name.encode()).hexdigest()[:8]}"


def unique_slugs[R](slugs: list[str], rank: list[R]) -> list[str]:
    """Make slugs unique within one folder, so items never share an output directory.

    Among items with the same slug, the one with the lowest ``rank`` keeps it and the others get
    ``-2``, ``-3``, … in rank order. Suffixes skip every slug in the folder, so an item that is
    really named ``photo-2`` keeps its name. Slugs without duplicates are returned unchanged.

    Args:
        slugs: One slug per item, in folder order.
        rank: One sortable key per item (e.g. capture time); ties keep folder order.
    """
    result = list(slugs)
    taken = set(slugs)
    groups: dict[str, list[int]] = {}
    for i, slug in enumerate(slugs):
        groups.setdefault(slug, []).append(i)

    for slug, members in groups.items():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda i: (rank[i], i))
        n = 2
        for i in ordered[1:]:
            while f"{slug}-{n}" in taken:
                n += 1
            result[i] = f"{slug}-{n}"
            taken.add(result[i])
    return result


def site_path(site: Path, url: str) -> Path:
    """Join a generated URL onto ``_site``, refusing anything that would land outside it."""
    path = (site / url).resolve()
    if not path.is_relative_to(site.resolve()):
        raise ValueError(f"refusing to write outside {site}: {url!r}")
    return path


def href(url: str) -> str:
    """Percent-encode a generated URL for use in HTML (ASCII slugs come out unchanged)."""
    return quote(url, safe="/.-")


def sequence_frames(directory: Path) -> list[Path]:
    """Image files of an image-sequence folder, sorted; hidden files (macOS ``._*``) excluded."""
    return sorted(
        f
        for f in directory.iterdir()
        if f.suffix.lower() in (".jpg", ".jpeg", ".gif", ".png") and not f.name.startswith(".")
    )


def strip_numeric_prefix(name: str) -> str:
    """Strip numeric prefix from name.

    Matches: sed -e 's/^[0-9]*//' | sed -e 's/^[[:space:]]*//;s/[[:space:]]*$//'

    Args:
        name: Input name.

    Returns:
        Name with numeric prefix removed and whitespace stripped.

    Examples:
        >>> strip_numeric_prefix("01 Mountains")
        'Mountains'
        >>> strip_numeric_prefix("123abc")
        'abc'
        >>> strip_numeric_prefix("  456  ")
        ''
    """
    result = re.sub(r"^[0-9]*", "", name).strip()
    return result if result else name
