import pytest

from z7_sentineltray.email_sender import DiskEmailQueue, EmailQueued, QueueingEmailSender


def test_disk_email_queue_enqueue_and_drain(tmp_path):
    queue_path = tmp_path / "queue.json"
    queue = DiskEmailQueue(
        queue_path,
        max_items=10,
        max_age_seconds=3600,
        max_attempts=3,
        retry_base_seconds=1,
    )

    queue.enqueue("hello")
    stats = queue.get_stats()
    assert stats.queued == 1

    sent = []

    def send_func(message: str) -> None:
        sent.append(message)

    drain_stats = queue.drain(send_func)
    assert drain_stats.sent == 1
    assert sent == ["hello"]
    assert queue.get_stats().queued == 0


def test_queueing_sender_enqueues_on_failure(tmp_path):
    queue_path = tmp_path / "queue.json"
    queue = DiskEmailQueue(
        queue_path,
        max_items=10,
        max_age_seconds=3600,
        max_attempts=3,
        retry_base_seconds=1,
    )

    class FailingSender:
        def send(self, _message: str) -> None:
            raise RuntimeError("network down")

    sender = QueueingEmailSender(sender=FailingSender(), queue=queue)

    with pytest.raises(EmailQueued):
        sender.send("payload")

    assert queue.get_stats().queued == 1


def test_queueing_sender_cumulative_and_get_stats(tmp_path):
    queue_path = tmp_path / "queue.json"
    queue = DiskEmailQueue(
        queue_path,
        max_items=10,
        max_age_seconds=3600,
        max_attempts=3,
        retry_base_seconds=1,
    )

    class FakeSMTPSender:
        def __init__(self):
            self.fail = False
            self.sends = 0

        def send(self, _message: str) -> None:
            if self.fail:
                raise RuntimeError("SMTP failure")
            self.sends += 1

    smtp_sender = FakeSMTPSender()
    sender = QueueingEmailSender(sender=smtp_sender, queue=queue)

    # 1. Successful send
    sender.send("msg1")
    stats = sender.get_queue_stats()
    assert stats.queued == 0
    assert stats.sent == 1
    assert stats.failed == 0

    # 2. Failed send (should enqueue and mark failure)
    smtp_sender.fail = True
    with pytest.raises(EmailQueued):
        sender.send("msg2")
    stats = sender.get_queue_stats()
    assert stats.queued == 1
    assert stats.sent == 1
    assert stats.failed == 1

    # 3. Successful drain (should clear queue and mark sent)
    smtp_sender.fail = False
    drain_stats = sender.drain()
    assert drain_stats.sent == 1
    stats = sender.get_queue_stats()
    assert stats.queued == 0
    assert stats.sent == 2
    assert stats.failed == 1

