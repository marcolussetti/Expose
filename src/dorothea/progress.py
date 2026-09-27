"""Progress display (#4), drawn with rich.

Only shown on an interactive terminal: in logs, CI or pipes the output stays plain text (and
nothing here runs), exactly as before. While the display is live, ordinary ``print`` output
appears above the bars.

- ``Reporter.live()`` wraps a build
- ``Reporter.task(description, total)`` counts things (files read, items encoded)
- ``Reporter.ffmpeg(label, duration)`` gives a callback for one ffmpeg run's progress in seconds
"""

import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)


class Task:
    """A progress bar for a count of things; does nothing when progress isn't shown."""

    def __init__(self, progress: Progress | None = None, task_id: TaskID | None = None):
        self._progress = progress
        self._id = task_id

    def advance(self, amount: float = 1) -> None:
        if self._progress is not None and self._id is not None:
            self._progress.advance(self._id, amount)

    def describe(self, description: str) -> None:
        if self._progress is not None and self._id is not None:
            self._progress.update(self._id, description=description)


class Reporter:
    """Shows progress bars when output is an interactive terminal."""

    def __init__(self, enabled: bool | None = None, console: Console | None = None):
        """Args:
        enabled: Force progress on or off (default: only when stdout is a terminal).
        console: Where to draw (tests pass one writing to a string).
        """
        self.enabled = sys.stdout.isatty() if enabled is None else enabled
        self._console = console
        self._progress: Progress | None = None

    @property
    def active(self) -> bool:
        """Progress is being drawn right now (inside ``live()``)."""
        return self._progress is not None

    @contextmanager
    def live(self) -> Iterator[None]:
        """Draw progress bars for the duration of the block (no-op when disabled)."""
        if not self.enabled or self._progress is not None:
            yield
            return
        progress = Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=self._console,
            redirect_stdout=True,
            redirect_stderr=True,
        )
        with progress:
            self._progress = progress
            try:
                yield
            finally:
                self._progress = None

    def task(self, description: str, total: int) -> Task:
        """A bar counting ``total`` things (no-op unless live)."""
        if self._progress is None:
            return Task()
        return Task(self._progress, self._progress.add_task(description, total=total))

    @contextmanager
    def ffmpeg(self, label: str, duration: float) -> Iterator[Callable[[float], None] | None]:
        """A callback reporting how many seconds of a video ffmpeg has written.

        Yields None when progress isn't live or the duration is unknown, which tells
        ``run_ffmpeg`` to run exactly as it does without progress. The bar is removed afterwards.
        """
        if self._progress is None or duration <= 0:
            yield None
            return
        progress = self._progress
        task_id = progress.add_task(f"  {label}", total=duration)

        def update(seconds: float) -> None:
            progress.update(task_id, completed=min(seconds, duration))

        try:
            yield update
        finally:
            progress.remove_task(task_id)
