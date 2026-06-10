#!/usr/bin/env bash
# start-regog.sh — boot the RealGog Flask app under Xvfb + tmux so it survives shell teardowns.
# Usage: ./start-regog.sh

set -u

# 1. Start Xvfb :99 if not already running
if ! pgrep -f 'Xvfb :99' > /dev/null 2>&1; then
  echo "[1/5] Starting Xvfb :99..."
  nohup Xvfb :99 -screen 0 1024x768x24 > /tmp/xvfb.log 2>&1 &
  sleep 2
else
  echo "[1/5] Xvfb :99 already running (PID $(pgrep -f 'Xvfb :99' | head -1))"
fi

# 2. Kill any existing regog tmux session
echo "[2/5] Killing any existing 'regog' tmux session..."
tmux kill-session -t regog 2>/dev/null || true
# Also kill any orphaned serve_report processes from previous non-tmux runs
pkill -9 -f 'serve_report.py' 2>/dev/null || true
sleep 1

# 3. Start the app in a tmux session that survives shell exit
echo "[3/5] Starting Flask app in tmux session 'regog'..."
tmux new-session -d -s regog 'cd /workspaces/REgog && DISPLAY=:99 python serve_report.py 2>&1 | tee /tmp/regog-app.log'
sleep 4

# 4. Verify
echo "[4/5] Verifying http://localhost:8080/ ..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8080/)
echo "        curl returned: $HTTP_CODE"

# 5. Report
if [ "$HTTP_CODE" = "200" ]; then
  echo "[5/5] RealGog ready"
  echo ""
  echo "  Open in browser:        http://localhost:8080/"
  echo "  tmux attach (live log): tmux attach -t regog"
  echo "  tail log directly:      tail -f /tmp/regog-app.log"
else
  echo "[5/5] FAILED"
  echo "  tail /tmp/regog-app.log"
  echo "  tmux attach -t regog    # see live output"
fi
