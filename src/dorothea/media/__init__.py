"""Media processing modules.

Provides abstractions for image, video, markdown, and color processing.
"""

from dorothea.media.colors import ColorExtractor
from dorothea.media.image import ImageProcessor
from dorothea.media.markdown import MarkdownProcessor
from dorothea.media.video import VideoProcessor

__all__ = [
    "ImageProcessor",
    "VideoProcessor",
    "MarkdownProcessor",
    "ColorExtractor",
]
