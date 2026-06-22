import smtplib
from contextlib import suppress

from z7_sentineltray.config import EmailConfig
from z7_sentineltray.email_sender import (
    EmailAuthError,
    QueueingEmailSender,
    SmtpEmailSender,
    build_sender,
)


def test_build_sender_returns_queue_sender(tmp_path) -> None:
    config = EmailConfig(
        smtp_host="smtp.local",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        from_address="alerts@example.com",
        to_addresses=["ops@example.com"],
        use_tls=True,
        timeout_seconds=30,
        subject="Z7_SentinelTray Notification",
        retry_attempts=0,
        retry_backoff_seconds=0,
    )

    sender = build_sender(config, queue_path=tmp_path / "queue.json")
    assert isinstance(sender, QueueingEmailSender)


def test_email_sender_retries(monkeypatch) -> None:
    config = EmailConfig(
        smtp_host="smtp.local",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        from_address="alerts@example.com",
        to_addresses=["ops@example.com"],
        use_tls=True,
        timeout_seconds=30,
        subject="Z7_SentinelTray Notification",
        retry_attempts=2,
        retry_backoff_seconds=0,
    )

    attempts = {"count": 0}

    class FakeSMTP:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, *_args) -> None:
            return None

        def send_message(self, _msg) -> None:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise smtplib.SMTPException("fail")

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    sender = SmtpEmailSender(config=config)
    sender.send("msg")
    assert attempts["count"] == 3


def test_email_sender_auth_failure_no_retry(monkeypatch) -> None:
    config = EmailConfig(
        smtp_host="smtp.local",
        smtp_port=587,
        smtp_username="user",
        smtp_password="bad",
        from_address="alerts@example.com",
        to_addresses=["ops@example.com"],
        use_tls=True,
        timeout_seconds=30,
        subject="Z7_SentinelTray Notification",
        retry_attempts=2,
        retry_backoff_seconds=0,
    )

    attempts = {"count": 0}

    class FakeSMTP:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, *_args) -> None:
            attempts["count"] += 1
            raise smtplib.SMTPAuthenticationError(534, b"auth")

        def send_message(self, _msg) -> None:
            return None

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    sender = SmtpEmailSender(config=config)
    with suppress(EmailAuthError):
        sender.send("msg")

    assert attempts["count"] == 1


def test_email_sender_subject_and_body(monkeypatch) -> None:
    config = EmailConfig(
        smtp_host="smtp.local",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        from_address="alerts@example.com",
        to_addresses=["ops@example.com"],
        use_tls=True,
        timeout_seconds=30,
        subject="Notification",
        retry_attempts=0,
        retry_backoff_seconds=0,
    )

    captured = {"message": None}

    class FakeSMTP:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, *_args) -> None:
            return None

        def send_message(self, msg) -> None:
            captured["message"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    sender = SmtpEmailSender(config=config)
    sender.send("info: test send")

    msg = captured["message"]
    assert msg is None


def test_email_sender_match_subject(monkeypatch) -> None:
    config = EmailConfig(
        smtp_host="smtp.local",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        from_address="alerts@example.com",
        to_addresses=["ops@example.com"],
        use_tls=True,
        timeout_seconds=30,
        subject="Notification",
        retry_attempts=0,
        retry_backoff_seconds=0,
    )

    captured = {"message": None}

    class FakeSMTP:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, *_args) -> None:
            return None

        def send_message(self, msg) -> None:
            captured["message"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    sender = SmtpEmailSender(config=config)
    sender.send("match payload")

    msg = captured["message"]
    assert msg is not None
    assert msg["Subject"] == "Z7_SentinelTray — Correspondência Detectada"


def test_email_sender_error_subject(monkeypatch) -> None:
    config = EmailConfig(
        smtp_host="smtp.local",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        from_address="alerts@example.com",
        to_addresses=["ops@example.com"],
        use_tls=True,
        timeout_seconds=30,
        subject="Notification",
        retry_attempts=0,
        retry_backoff_seconds=0,
    )

    captured = {"message": None}

    class FakeSMTP:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, *_args) -> None:
            return None

        def send_message(self, msg) -> None:
            captured["message"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    sender = SmtpEmailSender(config=config)
    sender.send("error: failure")

    msg = captured["message"]
    assert msg is not None
    assert msg["Subject"] == "Z7_SentinelTray — Erro Detectado"
