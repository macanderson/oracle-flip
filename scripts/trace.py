"""UserPromptSubmit and PostToolUse hook: appends message and tool_call events to the trace."""

from __future__ import annotations

import sys

from common import content_fields, load_state, log, read_event, save_state, write_event


def tool_call_fields(event: dict) -> dict:
    output = content_fields("output", event.get("tool_response", {}))
    output["output_truncated"] = output.pop("truncated")
    return {
        "tool_name": event.get("tool_name"),
        "tool_use_id": event.get("tool_use_id"),
        "duration_ms": event.get("duration_ms"),
        **content_fields("input", event.get("tool_input", {})),
        **output,
    }


def main() -> int:
    event = read_event()
    if event is None:
        return 0
    session_id = event["session_id"]
    state = load_state(session_id)
    kind = event.get("hook_event_name")

    if kind == "UserPromptSubmit":
        state.turn += 1
        write_event(session_id, "message", turn=state.turn, role="user", **content_fields("text", event.get("prompt", "")))
    elif kind == "PostToolUse":
        state.turn += 1
        write_event(session_id, "tool_call", turn=state.turn, **tool_call_fields(event))
    else:
        log(f"unexpected event {kind!r} routed to trace.py")
        return 0

    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
