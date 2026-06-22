"""CLI entrypoint for Z7_SentinelTray console app."""

from pathlib import Path
import sys


def _ensure_src_on_path() -> None:
    root = Path(__file__).resolve().parent
    src_path = root / "src"
    src_value = str(src_path)
    if src_value not in sys.path:
        sys.path.insert(0, src_value)


_ensure_src_on_path()

from z7_sentineltray.entrypoint import main


if __name__ == "__main__":
    raise SystemExit(main())
