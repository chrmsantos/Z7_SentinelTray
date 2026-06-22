from pathlib import Path

from z7_sentineltray.dpapi_utils import load_secret, save_secret


def test_dpapi_secret_roundtrip(tmp_path: Path) -> None:
    secret_path = tmp_path / "secret.dpapi"
    save_secret(secret_path, "example-secret")

    loaded = load_secret(secret_path)

    assert loaded == "example-secret"
