"""Entry point: `python -m uptimebeacon <command> [options]`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
