from __future__ import annotations

import importlib
import sys
from pathlib import Path


def test_main_inserts_src_on_path() -> None:
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    original_path = list(sys.path)
    sys.path = [item for item in sys.path if item != src_path]
    sys.modules.pop("z7_sentineltray", None)

    try:
        import main

        importlib.reload(main)
        assert src_path in sys.path
    finally:
        sys.path = original_path
