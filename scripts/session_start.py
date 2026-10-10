"""SessionStart hook: records the session and snapshots the task configuration.

The configuration is read here and stored in the session state. The Stop hook
reads the state, not the project, so changes the agent makes to
.oracle-flip/config.json during the session do not reach the gate. Nothing
slow runs here; the oracle baseline is computed on the first Stop.
"""

from __future__ import annotations

import os
import sys

from common import (
    DEFAULT_ORACLE_TIMEOUT_SECONDS,
    HARNESS,
    ConfigError,
    git_head,
    git_remote_url_hash,
    load_config,
    load_state,
    log,
    oracle_command_from_env,
    read_event,
    save_state,
    sha256,
    write_event,
)


def main() -> int:
    event = read_event()
    if event is None:
        return 0
    cwd = event.get("cwd")
    if not isinstance(cwd, str):
        log("SessionStart event has no cwd")
        return 0

    state = load_state(event["session_id"])
    config = None
    config_error = None
    try:
        config = load_config(cwd)
    except ConfigError as error:
        config_error = str(error)
        log(config_error)

    head = git_head(cwd)
    state.remote_url_hash = git_remote_url_hash(cwd)
    if config is not None and head is not None:
        state.task_id = config["task_id"]
        state.base_commit = config["base_commit"] or head
        state.max_attempts = config["max_attempts"]
        state.oracle_command = oracle_command_from_env()
        timeout = os.environ.get("CLAUDE_PLUGIN_OPTION_ORACLE_TIMEOUT_SECONDS", "")
        state.oracle_timeout_seconds = int(timeout) if timeout.isdigit() else DEFAULT_ORACLE_TIMEOUT_SECONDS
    save_state(state)

    write_event(
        event["session_id"],
        "session_start",
        cwd=cwd,
        base_commit=state.base_commit or head,
        remote_url_hash=state.remote_url_hash,
        model=event.get("model"),
        harness=HARNESS,
        source=event.get("source"),
        task_id=state.task_id,
        config_hash=sha256(str(config)) if config is not None else None,
        config_error=config_error,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
