# oracle-flip

A Claude Code plugin that writes every tool call to a trace file and refuses to let the agent say the work is done until a hidden oracle reports PASS. The oracle says PASS or FAIL and nothing else.

It is the reference plugin for [Building a continuous delivery system for fine-tuned open-source, open-weight models trained on your organization's traces](https://macanderson.com/research/continuous-delivery-of-fine-tuned-open-weight-models). [Chapter 8 of that book](https://macanderson.com/research/continuous-delivery-of-fine-tuned-open-weight-models/the-reference-plugin) walks through every file here.

## What it does

1. **SessionStart** records the session: the repository root, the base commit, the model, and the task id from `.oracle-flip/config.json` at that root. The configuration is snapshotted here, once. Edits the agent makes to it later do not reach the gate, and a resume or compaction does not move the base commit.
2. **UserPromptSubmit** and **PostToolUse** append `message` and `tool_call` events to `traces/<session_id>.jsonl` in the plugin's data directory. Inputs and outputs are redacted with secret patterns and truncated to 64 KB, with a hash of the original kept beside them.
3. **Stop** records the agent's final message, builds the diff against the base commit, and asks the oracle. On the first Stop it also asks for the baseline. On FAIL it blocks the stop with a fixed reason. On PASS it lets the agent stop and records the session as `flipped`. After `max_attempts` FAILs it records `no_flip` and lets the agent stop.
4. **SessionEnd** closes the trace with the outcome.

A **flip** is a session whose baseline verdict was FAIL and whose final verdict is PASS, with the existing test suite still passing. The flipped session's trace is a verified trajectory. `tools/export_sft.py` turns a directory of traces into training files.

## Install

```text
/plugin marketplace add macanderson/oracle-flip
/plugin install oracle-flip@macanderson
```

Or, to try it from a clone:

```sh
git clone https://github.com/macanderson/oracle-flip
claude --plugin-dir ./oracle-flip
```

Requires `python3` and `git`. The bundled oracle runner also needs `docker`.

## Configure

Four settings live in the plugin's user configuration (Claude Code asks for them when the plugin is enabled; they are stored outside every repository):

| Setting | Meaning |
|---|---|
| `oracle_command` | Command the Stop hook runs. Exit 0 is PASS, 1 is FAIL, anything else is an oracle error. Empty means the bundled `oracle/run.sh`. |
| `oracle_store` | Directory with one subdirectory per task id, each holding the hidden tests. See `oracle/example/`. |
| `oracle_image` | Container image for the bundled oracle, pinned by digest. |
| `oracle_timeout_seconds` | How long the Stop hook waits. Default 540. |

One file lives in the project the agent works in, `.oracle-flip/config.json`:

```json
{ "task_id": "billing-proration-rounding", "base_commit": null, "max_attempts": 6 }
```

`base_commit: null` means the commit at session start. Without this file the plugin only traces; it never blocks.

The allowlist and denylist of paths the diff may touch are **not** in the project. They live in the oracle store beside the hidden tests, because the project is the agent's to edit.

## The oracle

`oracle/run.sh` starts a container with `--network none`, a read-only mount of the task's hidden tests, a read-only mount of a repository mirror, and, in grade mode, a read-only mount of the diff. Inside, `oracle/grade.sh`:

1. Clones the mirror and checks out the base commit.
2. Filters the diff through the task's allowlist and denylist with `oracle/filter_diff.py`, logging every dropped path.
3. Applies what is left.
4. Copies the hidden tests in from the task directory. Never from the diff.
5. Runs the existing suite, then the hidden tests. Any failure is a FAIL.
6. Prints `tests_hash=` followed by a hash of the hidden test list, and exits 0 or 1.

Everything the oracle prints goes to a log directory in the oracle store. Only the exit code and the `tests_hash` line return to the gate, and the gate's reason to the agent is the same constant string every time.

In baseline mode the same run happens without a diff and must exit 1: the hidden tests fail and the existing suite passes. Exit 0 means there is no task. Exit 2 means the base commit is broken.

## What it does not do

- **It is not an air gap on one machine.** The container protects the oracle's run from the agent's working copy. It does not stop the agent's shell from reading the oracle store on the same host. Run the oracle on a host the agent cannot log into before you train on anything. The plugin's `oracle_command` setting is the seam: point it at a script that submits the diff to a job runner and waits for the bit.
- **It does not sign verdicts.** The `oracle_verdict` event has a `signature` field and the export tool has `--require-signature`. Signing needs a key on the oracle's side, which the reference runner does not have.
- **Redaction is a floor.** Patterns catch common secret shapes. Run a real secret scanner over the trace store before training.
- **The container path has not been run on the author's machine** at the time of writing. The hook scripts are tested by piping sample events into them (`python3 -m unittest discover tests`), and `claude plugin validate .` passes.
- **The harness has its own cap.** Claude Code ends the turn after eight consecutive Stop-hook continuations with no tool call in between. A session ended that way is recorded as `no_flip`. `max_attempts` defaults to 6 so the plugin, not the harness, usually decides.

## Trace format

One JSON Lines file per session. Event types: `session_start`, `message`, `tool_call`, `oracle_verdict`, `session_end`. The schema is in `schema/trace-event.schema.json`. Content fields are redacted; `_hash` fields hold the SHA-256 of the original.

## Export

```sh
python3 tools/export_sft.py --traces "$CLAUDE_PLUGIN_DATA/traces" --out ./dataset
```

Writes `sft.jsonl` (one chat per flipped session, with a per-turn `train` flag that masks user prompts and tool results) and `pairs.jsonl` (flipped versus not-flipped sessions on the same task, for preference optimization).

## Tests

```sh
python3 -m unittest discover tests
```

## License

MIT.
