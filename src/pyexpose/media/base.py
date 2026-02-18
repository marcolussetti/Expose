"""Base classes for media processors."""

from abc import ABC, abstractmethod
from pathlib import Path


class MediaProcessor(ABC):
    """Base class for media processors.

    Provides a common interface for processing different media types
    (images, videos, etc.).
    """

    @abstractmethod
    def process(self, input_path: Path, output_path: Path, **kwargs) -> None:
        """Process a media file.

        Args:
            input_path: Input file path.
            output_path: Output file path.
            **kwargs: Additional processing parameters.
        """
        pass
