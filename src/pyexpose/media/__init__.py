"""Media processing modules.

Provides abstractions for image, video, markdown, and color processing.
"""

from pyexpose.media.colors import ColorExtractor
from pyexpose.media.image import ImageProcessor
from pyexpose.media.markdown import MarkdownProcessor
from pyexpose.media.video import VideoProcessor

__all__ = [
    "ImageProcessor",
    "VideoProcessor",
    "MarkdownProcessor",
    "ColorExtractor",
]
