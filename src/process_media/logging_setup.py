"""Shared logging configuration.

Both the CLI entry point and the process-pool workers need a Rich-based
log handler; centralising the setup here keeps the configuration in a
single place and avoids subtle drifts between parent and worker output.
"""

from __future__ import annotations

import logging

from rich.logging import RichHandler


def setup_logging(level: int, *, show_path: bool = False) -> None:
    """Reset and reconfigure the root logger with a Rich handler.

    Existing handlers are removed first so calling ``setup_logging``
    multiple times (e.g. once for the CLI, then once per worker process)
    never produces duplicate output.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    rich_handler = RichHandler(
        rich_tracebacks=True,
        show_path=show_path,
        show_time=False,
        markup=False,
    )
    rich_handler.setLevel(level)
    root.addHandler(rich_handler)
    root.setLevel(level)
