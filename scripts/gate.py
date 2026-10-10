"""Stop hook: records the agent's final message, asks the oracle, and blocks the stop on FAIL.

Exit 0 with no output lets the agent stop. Exit 0 with a JSON decision of
"block" keeps it working. The reason is a constant; the oracle's output never
reaches the agent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from common import (
    BLOCK_REASON_ERROR,
    BLOCK_REASON_FAIL,
    SessionState,
    Verdict,
    content_fields,
    data_dir,
    load_state,
    log,
    read_event,
    run_oracle,
    save_state,
    write_diff,
    write_event,
)

OracleFn = Callable[..., Verdict]
DiffFn = Callable[[str, str, Path], str]


def allow() -> dict[str, Any] | None:
    return None


def block(reason: str) -> dict[str, Any]:
    return {"decision": "block", "reason": reason}


def record_verdict(state: SessionState, mode: str, verdict: Verdict, diff_hash: str | None) -> None:
    write_event(
        state.session_id,
        "oracle_verdict",
        attempt=state.attempts,
        mode=mode,
        verdict=verdict.verdict,
        tests_hash=verdict.tests_hash,
        image_digest=verdict.image_digest,
        diff_hash=diff_hash,
        duration_ms=verdict.duration_ms,
        error=verdict.error,
    )


def decide(event: dict[str, Any], state: SessionState, *, oracle: OracleFn = run_oracle, diff: DiffFn = write_diff) -> dict[str, Any] | None:
    """The gate's decision for one Stop event. Pure apart from the oracle and diff callables and the state it mutates."""
    message = event.get("last_assistant_message")
    if isinstance(message, str) and message:
        state.turn += 1
        write_event(state.session_id, "message", turn=state.turn, role="assistant", **content_fields("text", message))

    if state.task_id is None or state.base_commit is None:
        return allow()  # no oracle task in this session; the plugin only traces
    if state.outcome is not None:
        return allow()  # already decided for this session; never loop on a settled outcome

    common = dict(
        task_id=state.task_id,
        base_commit=state.base_commit,
        remote_url_hash=state.remote_url_hash,
        timeout_seconds=state.oracle_timeout_seconds,
    )

    if state.baseline is None:
        baseline = oracle(state.oracle_command, mode="baseline", diff_path=None, **common)
        state.baseline = baseline.verdict
        record_verdict(state, "baseline", baseline, None)
        if baseline.verdict == "PASS":
            state.outcome = "no_task"  # the hidden test already passes on the base commit
            return allow()
        if baseline.verdict == "ERROR":
            state.outcome = "oracle_error"
            return allow()

    cwd = state.repo_root or event.get("cwd")
    if not isinstance(cwd, str):
        return allow()
    diff_path = data_dir() / "diffs" / f"{state.session_id}-{state.attempts + 1}.patch"
    try:
        diff_hash = diff(cwd, state.base_commit, diff_path)
    except Exception as error:  # noqa: BLE001 - any failure to build the diff is an oracle error for this attempt
        log(f"could not build the diff: {error}")
        state.attempts += 1
        record_verdict(state, "grade", Verdict("ERROR", error="diff failed"), None)
        return block(BLOCK_REASON_ERROR) if state.attempts < state.max_attempts else allow()

    verdict = oracle(state.oracle_command, mode="grade", diff_path=diff_path, **common)
    state.attempts += 1
    record_verdict(state, "grade", verdict, diff_hash)

    if verdict.verdict == "PASS":
        state.outcome = "flipped"
        return allow()
    if state.attempts >= state.max_attempts:
        state.outcome = "no_flip"
        return allow()
    return block(BLOCK_REASON_FAIL if verdict.verdict == "FAIL" else BLOCK_REASON_ERROR)


def main() -> int:
    event = read_event()
    if event is None:
        return 0
    state = load_state(event["session_id"])
    try:
        decision = decide(event, state)
    finally:
        save_state(state)
    if decision is not None:
        sys.stdout.write(json.dumps(decision))
    return 0


if __name__ == "__main__":
    sys.exit(main())
