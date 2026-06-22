from z7_sentineltray.status import StatusStore


def test_status_tracks_monitor_failures_and_breakers() -> None:
    status = StatusStore()
    status.set_monitor_state("mon-a", failure_count=2, breaker_active=True)
    status.set_monitor_state("mon-b", failure_count=0, breaker_active=False)

    snapshot = status.snapshot()

    assert snapshot.monitor_failures["mon-a"] == 2
    assert snapshot.breaker_active_count == 1
