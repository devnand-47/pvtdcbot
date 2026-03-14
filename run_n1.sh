#!/usr/bin/env bash
cd /root/DCBOTS/C2NINJA
while true; do
  source venv/bin/activate
  echo "[BOT] Starting..."
  python bot.py
  echo "[BOT] Crashed with exit code $? — restarting in 5s..."
  sleep 5
done
