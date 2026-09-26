"""PyExpose - Static photography website generator.

A Python port of expose.sh that generates static photography/video galleries.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pyexpose")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0+unknown"

from pyexpose.generator import ExposeGenerator  # noqa: E402

__all__ = ["ExposeGenerator", "__version__"]
