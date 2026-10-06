#!/usr/bin/env bash
# setup_venv.sh — create the "jobs" virtual environment and install dependencies (macOS/Linux).
# Usage (from anywhere):  bash scripts/setup_venv.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x jobs/bin/python ]; then
    echo "Creating virtual environment 'jobs'..."
    python3 -m venv jobs
fi
jobs/bin/python -m pip install --upgrade pip
jobs/bin/python -m pip install -r requirements.txt

for pair in ".env.example:.env" "job_preference.example.md:job_preference.md" "resume_details.example.md:resume_details.md"; do
    src="${pair%%:*}"; dst="${pair##*:}"
    if [ -f "$src" ] && [ ! -f "$dst" ]; then
        cp "$src" "$dst"
        echo "Created $dst from $src - edit it with your details."
    fi
done
echo
echo "Done. Activate with:  source jobs/bin/activate"
