#!/usr/bin/env bash
# Runs inside the oracle container. Nothing here is reachable from the agent's host.
#
# Mounts:   /mirror (repository mirror, read-only)   /task (hidden tests and lists, read-only)
#           /in/diff.patch (grade mode, read-only)   /log (written here, read by people)
# Task dir: hidden/        files copied into the checkout after the diff is applied
#           allowlist      globs of paths the diff may touch, one per line
#           denylist       globs of paths the diff may never touch
#           tests.txt      the identifiers of the hidden tests, for tests_hash
#           run_suite.sh   runs the existing suite; exit 0 when it passes
#           run_hidden.sh  runs the hidden tests; exit 0 when they pass
#
# Exit codes: 0 PASS, 1 FAIL, 2 the base commit is unfit (suite fails before any change),
#             3 the diff does not apply.
set -uo pipefail

reason() { echo "$1" >> /log/reason.txt; }

mkdir -p /work && cd /work
git clone -q /mirror repo && cd repo && git checkout -q "$ORACLE_BASE_COMMIT" || { reason "checkout failed"; exit 2; }

if [ "$ORACLE_MODE" = "grade" ]; then
  python3 /oracle/filter_diff.py --allow-file /task/allowlist --deny-file /task/denylist \
    < /in/diff.patch > /tmp/filtered.patch 2> /log/dropped.txt
  if [ -s /tmp/filtered.patch ]; then
    git apply --check /tmp/filtered.patch 2>> /log/apply.txt || { reason "diff does not apply"; exit 3; }
    git apply /tmp/filtered.patch 2>> /log/apply.txt || { reason "diff failed to apply"; exit 3; }
  else
    reason "diff touched no allowed path"
  fi
fi

# The hidden tests come from the task store, never from the diff.
cp -R /task/hidden/. ./
echo "tests_hash=$(sort /task/tests.txt | sha256sum | cut -d' ' -f1)"

bash /task/run_suite.sh > /log/suite.txt 2>&1
suite=$?
bash /task/run_hidden.sh > /log/hidden.txt 2>&1
hidden=$?

if [ "$ORACLE_MODE" = "baseline" ]; then
  # A good baseline is: the existing suite passes and the hidden tests fail.
  [ "$suite" -eq 0 ] || { reason "existing suite fails on the base commit"; exit 2; }
  [ "$hidden" -eq 0 ] && { reason "hidden tests already pass on the base commit"; exit 0; }
  reason "baseline FAIL as expected"
  exit 1
fi

[ "$suite" -eq 0 ] || { reason "existing suite fails after the change"; exit 1; }
[ "$hidden" -eq 0 ] || { reason "hidden tests fail after the change"; exit 1; }
reason "PASS"
exit 0
