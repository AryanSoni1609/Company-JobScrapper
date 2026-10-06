#!/usr/bin/env bash
# run_daemon.sh — run the scheduler in this terminal (Ctrl+C to stop).
set -euo pipefail
cd "$(dirname "$0")/.."
exec jobs/bin/python -m jobscraper daemon
