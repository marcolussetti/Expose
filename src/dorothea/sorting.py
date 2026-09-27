"""Sort orders for galleries and photos (the ``sort`` setting / ``--sort``).

- ``name``: plain name order, like expose.sh's ``sort`` (the default; parity)
- ``natural``: numbers compare as numbers, case-insensitively (``1, 2, 10`` rather than ``1, 10, 2``)
- ``capture``: when photos were taken (EXIF capture time, else file time); folders sort by their
  earliest photo, so the site follows the trip
- each with a ``-desc`` variant for newest/highest first
"""

import re
from collections.abc import Callable

SORT_MODES = ("name", "name-desc", "natural", "natural-desc", "capture", "capture-desc")

_DIGITS = re.compile(r"(\d+)")


def natural_key(name: str) -> list[int | str]:
    """Sort key where digit runs compare numerically: ``img2`` < ``img10``.

    Splitting on digits always alternates text and numbers (starting with text), so keys of
    different names compare element by element without mixing types.
    """
    return [int(part) if i % 2 else part.casefold() for i, part in enumerate(_DIGITS.split(name))]


def sort_items[T](
    items: list[T], mode: str, name: Callable[[T], str], taken_at: Callable[[T], float]
) -> list[T]:
    """Reorder ``items`` (given in name order) according to ``mode``.

    Sorting is stable, so items that tie keep their name order.

    Args:
        items: Items in plain name order (what ``name`` mode returns unchanged).
        mode: One of ``SORT_MODES``.
        name: The name natural sorting compares.
        taken_at: When the item was taken (POSIX time), for ``capture`` sorting.
    """
    base = mode.removesuffix("-desc")
    descending = mode.endswith("-desc")
    if base == "natural":
        ordered = sorted(items, key=lambda item: natural_key(name(item)), reverse=descending)
    elif base == "capture":
        ordered = sorted(items, key=taken_at, reverse=descending)
    else:
        ordered = list(reversed(items)) if descending else list(items)
    return ordered
