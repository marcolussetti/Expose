"""Command-line interface for PyExpose.

Handles argument parsing, dependency checking, signal handlers,
and orchestrates the generation process.
"""

import argparse
import atexit
import signal
import sys
from pathlib import Path

from pyexpose.config import Config
from pyexpose.generator import ExposeGenerator


def check_dependencies():
    """Check required dependencies are available.

    Raises:
        SystemExit: If required dependencies are missing.
    """
    # ImageMagick (convert/identify) no longer required — using Pillow.
    # FFmpeg still required for video encoding.
    pass


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(description="Expose - Static photography website generator")
    parser.add_argument(
        "-d",
        "--draft",
        action="store_true",
        help="Draft mode: single resolution, fast encoding",
    )
    args = parser.parse_args()

    check_dependencies()

    topdir = Path.cwd()
    # scriptdir should be the project root where theme directories live
    scriptdir = Path(__file__).parent.parent.parent.resolve()

    config = Config.load(topdir, scriptdir)

    if args.draft:
        config.apply_draft_mode()

    generator = ExposeGenerator(topdir, scriptdir, config, draft=args.draft)

    # Set up signal handlers for cleanup
    def signal_handler(sig, frame):
        generator.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(generator.cleanup)

    generator.run()


if __name__ == "__main__":
    main()
