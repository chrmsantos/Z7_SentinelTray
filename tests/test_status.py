from z7_sentineltray.status import StatusStore, format_status


def test_status_store_snapshot() -> None:
    store = StatusStore()
    store.set_running(True)
    store.set_paused(True)
    store.set_last_scan("2026-01-19T23:00:00-03:00")
    store.set_last_match("2026-01-19T23:00:00-03:00")
    store.set_last_send("2026-01-19T23:00:00-03:00")
    store.set_last_error("2026-01-19T23:00:00-03:00")
    store.set_last_healthcheck("2026-01-19T23:00:00-03:00")
    store.set_uptime_seconds(42)
    store.increment_error_count()
    store.increment_error_count()

    snapshot = store.snapshot()
    assert snapshot.running is True
    assert snapshot.paused is True
    assert snapshot.last_scan == "2026-01-19T23:00:00-03:00"
    assert snapshot.last_match == "2026-01-19T23:00:00-03:00"
    assert snapshot.last_send == "2026-01-19T23:00:00-03:00"
    assert snapshot.last_error == "2026-01-19T23:00:00-03:00"
    assert snapshot.last_healthcheck == "2026-01-19T23:00:00-03:00"
    assert snapshot.uptime_seconds == 42
    assert snapshot.error_count == 2

    text = format_status(
        snapshot,
        window_title_regex="APP",
        phrase_regex="ALERT",
        poll_interval_seconds=60,
    )
    assert "Em execução: sim" in text
    assert "19-01-2026 - 23:00" in text
    assert "Janela monitorada: APP" in text
    assert "Texto monitorado: ALERT" in text
    assert "Próxima verificação: 19-01-2026 - 23:01" in text
    assert "Última detecção: 19-01-2026 - 23:00" in text
