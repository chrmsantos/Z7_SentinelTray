# Maintenance log

## 2026-01-27
- Removed obsolete log artifacts to keep only the five most recent log files per routine.
- Purged generated test and coverage cache artifacts from the repository.
- Fixed portable runtime preparation to install pip correctly before downloading wheels.

## 2026-01-28
- Detector now includes the window title text in scans and treats whitespace-only phrases as empty.
- Window minimization respects allow_window_restore to reduce desktop disruption.
- Added unit tests for phrase handling and regex validation.

## 2026-02-05
- SMTP password prompt now skips when env credentials are already set.
- Script log retention aligned to keep only the 3 most recent files.
- Window restore/maximize now retries restore and enforces allow_window_restore.
- Added a minimal green tray icon using pywin32.
- Updated pywin32 pin for Python 3.14 compatibility.
- Encrypted configs may now use stored smtp_password when env is missing.
- Added startup SMTP validation and runtime checksum sampling.
- Status now exposes per-monitor failures and breaker counts.

## 2026-07-01 (6.5.1)
- Desativado o circuit breaker e backoff do monitor em caso de erros no detector, garantindo que o aplicativo continue tentando ler a janela normalmente.
- Desativado o backoff exponencial do loop principal de verificação para manter o tempo de varredura constante mesmo com ocorrência de erros.

