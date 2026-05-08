# heartbeat — dispatched job

Trivial example of the Mac→DGX dispatch contract. Writes a timestamped line to
`~/logs/hsa-receipt-system-heartbeat.log` on DGX every 5 minutes.

Also useful as a liveness signal: if the log stops growing, the systemd-user
runtime on DGX has a problem worth investigating.

## Why this lives in `hsa-receipt-system/`

Convention: each repo owns its dispatched jobs in `<repo>/scripts/dgx/<job>/`,
read by `_meta/scripts/dispatch-to-dgx.sh`. heartbeat is the **bootstrap
example** — it landed here because HSA was the active repo when the dispatch
protocol shipped. It's not HSA-specific. Future DGX-only health jobs may move
to `_meta/scripts/dgx-jobs/` (would need a small extension to the dispatcher).

## Prerequisites on DGX

- `~/dgx-infra/scripts/install-job.sh` exists (from
  [dgx-infra@bd730af](https://github.com/minghsuy/dgx-infra/commit/bd730af))
- `status-notify-quiet@.service` is installed (existing user-mode unit in
  `~/dgx-infra/systemd-user/`) — provides the ntfy.sh push on `OnFailure=`

## Dispatch

```bash
# Register as a 5-minute timer:
~/Documents/Github/_meta/scripts/dispatch-to-dgx.sh hsa-receipt-system heartbeat --register

# Run once (no timer registration):
~/Documents/Github/_meta/scripts/dispatch-to-dgx.sh hsa-receipt-system heartbeat --once

# Remove:
~/Documents/Github/_meta/scripts/dispatch-to-dgx.sh hsa-receipt-system heartbeat --remove

# Verify removal (should print nothing):
ssh miyang@spark-d1bb 'systemctl --user list-timers --all | grep heartbeat || echo "no heartbeat timer"'
```

## Inspect

```bash
# Tail the log on DGX:
ssh miyang@spark-d1bb 'tail -10 ~/logs/hsa-receipt-system-heartbeat.log'

# Check next-fire from Mac (via state surface):
dgx-status                         # surfaces dispatched-job count
gh gist view <id> --raw | jq .dispatched_jobs

# Or directly:
ssh miyang@spark-d1bb 'systemctl --user list-timers dgx-job-hsa-receipt-system-heartbeat.timer'
```
