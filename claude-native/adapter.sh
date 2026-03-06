#!/bin/bash
# adapter.sh — automation assistant Native Engine Adapter
# Uruchamia sesję automation assistant dla zespołu z zadaniem.
#
# Usage:
#   ./adapter.sh run <team_id> <task_json>
#   ./adapter.sh status <task_id>
#   ./adapter.sh stop <task_id>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
TASKS_DIR="$PROJECT_DIR/.engine-tasks"
mkdir -p "$TASKS_DIR"

COMMAND="${1:?Usage: adapter.sh run|status|stop <args>}"

case "$COMMAND" in
  run)
    TEAM_ID="${2:?Missing team_id}"
    TASK_JSON="${3:?Missing task JSON}"
    TEAM_DIR="$PROJECT_DIR/teams/$TEAM_ID"

    if [ ! -d "$TEAM_DIR" ]; then
      echo '{"error": "Team not found: '"$TEAM_ID"'"}' >&2
      exit 1
    fi

    TASK_ID="task-$(date +%s)-$(openssl rand -hex 4)"
    TASK_FILE="$TASKS_DIR/$TASK_ID.json"
    LOG_FILE="$TASKS_DIR/$TASK_ID.log"

    # Extract prompt from task JSON
    PROMPT=$(echo "$TASK_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('prompt', json.load(sys.stdin).get('description', '')))" 2>/dev/null || echo "$TASK_JSON")

    # Record task start
    cat > "$TASK_FILE" << EOF
{
  "task_id": "$TASK_ID",
  "team_id": "$TEAM_ID",
  "engine": "llm-native",
  "status": "running",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)",
  "prompt": $(echo "$PROMPT" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read().strip()))" 2>/dev/null || echo "\"$PROMPT\"")
}
EOF

    echo "{\"task_id\": \"$TASK_ID\", \"status\": \"running\", \"team\": \"$TEAM_ID\", \"engine\": \"llm-native\"}"

    # Run automation assistant in background with team context
    (
      cd "$TEAM_DIR"
      llm --print "$PROMPT" > "$LOG_FILE" 2>&1
      EXIT_CODE=$?

      # Update task status
      python3 -c "
import json, sys
with open('$TASK_FILE') as f: task = json.load(f)
task['status'] = 'completed' if $EXIT_CODE == 0 else 'failed'
task['ended_at'] = '$(date -u +%Y-%m-%dT%H:%M:%S.000Z)'
task['exit_code'] = $EXIT_CODE
with open('$TASK_FILE', 'w') as f: json.dump(task, f, indent=2)
" 2>/dev/null
    ) &
    ;;

  status)
    TASK_ID="${2:?Missing task_id}"
    TASK_FILE="$TASKS_DIR/$TASK_ID.json"
    if [ ! -f "$TASK_FILE" ]; then
      echo '{"error": "Task not found"}' >&2
      exit 1
    fi
    cat "$TASK_FILE"
    ;;

  stop)
    TASK_ID="${2:?Missing task_id}"
    # Find and kill the llm process for this task
    pkill -f "llm.*$TASK_ID" 2>/dev/null || true
    TASK_FILE="$TASKS_DIR/$TASK_ID.json"
    if [ -f "$TASK_FILE" ]; then
      python3 -c "
import json
with open('$TASK_FILE') as f: task = json.load(f)
task['status'] = 'stopped'
task['ended_at'] = '$(date -u +%Y-%m-%dT%H:%M:%S.000Z)'
with open('$TASK_FILE', 'w') as f: json.dump(task, f, indent=2)
" 2>/dev/null
    fi
    echo '{"task_id": "'"$TASK_ID"'", "status": "stopped"}'
    ;;

  *)
    echo "Usage: adapter.sh run|status|stop <args>" >&2
    exit 1
    ;;
esac
