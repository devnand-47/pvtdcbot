#!/usr/bin/env bash
cd /root/DCBOTS/C2NINJA
while true; do
  source venv/bin/activate
  echo "[DASH] Starting..."
  uvicorn dashboard:app --host 0.0.0.0 --port 8000
  echo "[DASH] Crashed with exit code $? — restarting in 5s..."
  sleep 5
done
