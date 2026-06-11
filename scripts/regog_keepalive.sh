#!/usr/bin/env bash
# regog_keepalive.sh — auto-restart the REGOG Flask app on any death.
# Solves the codespace-idle-kill problem: after ~20 min of inactivity the
# container reaps the process, the log just stops, and curl returns 000.
# Wrapping in `while true` makes the app self-healing regardless of cause.
#
# Usage:  nohup bash scripts/regog_keepalive.sh > /tmp/regog-app.log 2>&1 < /dev/null & disown
# Stop:   pkill -f regog_keepalive.sh
# Logs:   /tmp/regog-app.log

cd /workspaces/regogv8
echo $$ > /tmp/regog-keepalive.pid
while true; do
    python3 serve_report.py
    echo "[keepalive $(date -Is)] serve_report.py exited with code $? — restarting in 2s" >> /tmp/regog-app.log
    sleep 2
done
