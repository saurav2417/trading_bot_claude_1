#!/usr/bin/env bash
# Run the autonomous trading loop. Restarts on crash with backoff.
set -u
cd "$(dirname "$0")/.."

while true; do
    PYTHONPATH=src python3 -m tradebot.cli run
    code=$?
    echo "tradebot exited with code $code; restarting in 60s (Ctrl-C to stop)"
    sleep 60
done
