#!/usr/bin/env bash
set -uo pipefail

uvicorn codebase_qa.api.app:app --host 127.0.0.1 --port 8000 &
backend=$!

streamlit run frontend/app.py \
    --server.port 7860 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false &
frontend=$!

trap 'kill "$backend" "$frontend" 2>/dev/null' TERM INT

wait -n "$backend" "$frontend"
status=$?
echo "a process exited with status $status, stopping the container" >&2
kill "$backend" "$frontend" 2>/dev/null
wait
if [ "$status" -eq 0 ]; then
    exit 1
fi
exit "$status"
