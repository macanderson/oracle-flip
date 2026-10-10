#!/usr/bin/env bash
# Reference oracle runner. Runs grade.sh inside a container with no network.
#
# Called by the Stop hook with these variables set:
#   ORACLE_MODE          baseline | grade
#   ORACLE_TASK_ID       the task whose hidden tests to run
#   ORACLE_BASE_COMMIT   the commit the agent started from
#   ORACLE_DIFF          path to the agent's diff (grade mode only)
# Reads from the plugin's user settings:
#   CLAUDE_PLUGIN_OPTION_ORACLE_STORE   directory with one subdirectory per task id
#   CLAUDE_PLUGIN_OPTION_ORACLE_IMAGE   container image pinned by digest
#
# Exit 0 = PASS, 1 = FAIL, anything else = the oracle could not grade.
# Prints tests_hash=... and image_digest=... on stdout. Everything else goes to the log directory.
set -euo pipefail

store="${CLAUDE_PLUGIN_OPTION_ORACLE_STORE:-${ORACLE_STORE:-}}"
image="${CLAUDE_PLUGIN_OPTION_ORACLE_IMAGE:-${ORACLE_IMAGE:-}}"
[ -n "$store" ] || { echo "oracle store not configured" >&2; exit 3; }
[ -n "$image" ] || { echo "oracle image not configured" >&2; exit 3; }
task_dir="$store/$ORACLE_TASK_ID"
[ -d "$task_dir" ] || { echo "no hidden tests for task $ORACLE_TASK_ID" >&2; exit 3; }
mirror="${ORACLE_MIRROR:-$store/.mirror}"
[ -d "$mirror" ] || { echo "no repository mirror at $mirror" >&2; exit 3; }

log_dir="$store/.log/$ORACLE_TASK_ID/$(date -u +%Y%m%dT%H%M%SZ)-$ORACLE_MODE"
mkdir -p "$log_dir"

args=(run --rm --network none
      -e TZ=UTC -e LC_ALL=C.UTF-8 -e PYTHONHASHSEED=0 -e SOURCE_DATE_EPOCH=1700000000
      -e ORACLE_MODE="$ORACLE_MODE" -e ORACLE_BASE_COMMIT="$ORACLE_BASE_COMMIT"
      -v "$task_dir:/task:ro" -v "$mirror:/mirror:ro" -v "$log_dir:/log")
if [ "$ORACLE_MODE" = "grade" ]; then
  [ -f "${ORACLE_DIFF:-}" ] || { echo "no diff file" >&2; exit 3; }
  args+=(-v "$ORACLE_DIFF:/in/diff.patch:ro")
fi

echo "image_digest=$image"
# Only the exit code and the tests_hash line return to the gate. The rest is the oracle's log.
set +e
docker "${args[@]}" "$image" bash /oracle/grade.sh > "$log_dir/stdout.txt" 2> "$log_dir/stderr.txt"
status=$?
set -e
grep -E '^tests_hash=' "$log_dir/stdout.txt" || true
exit "$status"
