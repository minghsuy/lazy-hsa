#!/usr/bin/env bash
# Heartbeat: write a timestamped line to ~/logs/hsa-receipt-system-heartbeat.log
# every time the unit fires. Trivial demonstration of the dispatch contract;
# also a useful liveness signal — if this stops appending, something's wrong
# with the systemd-user runtime on DGX.
set -euo pipefail

LOG="$HOME/logs/hsa-receipt-system-heartbeat.log"
mkdir -p "$(dirname "$LOG")"

ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
loadavg=$(awk '{print $1, $2, $3}' /proc/loadavg)
echo "$ts heartbeat ok (load: $loadavg)" >> "$LOG"

# Keep the log bounded. Race: two simultaneous timer fires (e.g., suspend
# resume with Persistent=true catching up) could both pass the line-count
# check and one mv overwrites the other's partial. Acceptable for a 5-min
# heartbeat — worst case loses ~500 lines of history, no functional impact.
if [[ $(wc -l < "$LOG") -gt 1000 ]]; then
    tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
