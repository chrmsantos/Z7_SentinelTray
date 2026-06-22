import types

from z7_sentineltray import app


def test_apply_execution_state_no_kernel32(monkeypatch) -> None:
    dummy = types.SimpleNamespace()
    monkeypatch.setattr(app, "ctypes", dummy)

    assert app._apply_execution_state(True) is False
    assert app._apply_execution_state(False) is False
