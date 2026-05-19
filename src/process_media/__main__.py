"""Entry point for ``python -m process_media``."""

from __future__ import annotations

from .cli import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
