# Local templates

## Purpose

Use these files as reference to create local files on the user machine.
The installer copies templates/local/config.local.yaml to the data folder when the file does not exist.

## How to use

1. Create the configuration file at:
   %Z7_SENTINELTRAY_DATA_DIR%\config.local.yaml (when defined)
   or %LOCALAPPDATA%\ZWave\Tmp\Z7_SentinelTray\Config\config.local.yaml
2. Fill the required fields and restart the application.
3. state.json is only an example of the local history format.
4. The editor always syncs with the official template, merging existing values into the latest structure.
5. Use the console command [R] to run a template reconciliation dry-run before applying changes.

## Regex (wildcards)

- `.*` matches any sequence of characters.
- `.` matches a single character.
- `?` makes the previous character optional.
- `[A-Z]` matches a set/range.
- `\d` for digits, `\s` for spaces, `^` start and `$` end.

Examples:

- window_title_regex: '^App\\.Monitor\\..*'
- phrase_regex: 'PROTOCOLS?\\s+NOT\\s+RECEIVED'
- phrase_regex: 'ALERT|CRITICAL'

Notes:

- window_title_regex uses regex search (partial match by default). Use ^...$ if you need an exact match.

## Multiple monitors

Use the `monitors` key to define multiple title + text pairs.
Each item must include a full `email` block.

## Notes

- Do not include real credentials in sample files.
- Additional robustness parameters available: min_repeat_seconds; error_notification_cooldown_seconds; window_error_backoff_base_seconds / window_error_backoff_max_seconds; window_error_circuit_threshold / window_error_circuit_seconds; email_queue_file / email_queue_max_items / email_queue_max_age_seconds; email_queue_max_attempts / email_queue_retry_base_seconds.
