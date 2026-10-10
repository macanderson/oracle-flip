"""SessionEnd hook: closes the trace with the session's outcome.

A session that recorded attempts but never settled an outcome ended without the
gate's say-so: the harness's continuation cap, a user interrupt, or an exit. It is
recorded as no_flip so it is never mistaken for a flip.
"""

from __future__ import annotations

import sys

from common import load_state, read_event, save_state, write_event


def main() -> int:
    event = read_event()
    if event is None:
        return 0
    state = load_state(event["session_id"])
    if state.outcome is None:
        state.outcome = "no_flip" if state.attempts > 0 else "aborted"
        save_state(state)
    write_event(
        event["session_id"],
        "session_end",
        outcome=state.outcome,
        attempts=state.attempts,
        baseline=state.baseline,
        reason=event.get("reason"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
