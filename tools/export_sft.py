"""Turns traces and verdicts into training files.

    python3 tools/export_sft.py --traces ~/.claude/plugins/data/oracle-flip/traces --out ./dataset

Writes two JSON Lines files:

  sft.jsonl    one record per flipped session: a chat with tool calls and a per-turn
               `train` flag. User prompts and tool results are marked train=false.
  pairs.jsonl  one record per (flipped, not flipped) pair of sessions on the same task,
               for preference optimization.

Sessions without a session_end, without a verdict, or with an outcome other than
flipped are excluded from sft.jsonl. With --require-signature, verdicts without a
`signature` field are treated as missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_session(path: Path) -> list[dict[str, Any]]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def to_chat(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Builds the chat turns in order. Only assistant turns are marked for training."""
    turns: list[dict[str, Any]] = []
    for event in events:
        kind = event["type"]
        if kind == "message":
            turns.append({"role": event["role"], "content": event["text_redacted"], "train": event["role"] == "assistant"})
        elif kind == "tool_call":
            turns.append(
                {
                    "role": "assistant",
                    "tool_call": {"name": event["tool_name"], "id": event.get("tool_use_id"), "input": event["input_redacted"]},
                    "train": True,
                }
            )
            turns.append({"role": "tool", "tool_call_id": event.get("tool_use_id"), "content": event["output_redacted"], "train": False})
    return turns


def summarize(events: list[dict[str, Any]], require_signature: bool) -> dict[str, Any] | None:
    start = next((e for e in events if e["type"] == "session_start"), None)
    end = next((e for e in events if e["type"] == "session_end"), None)
    verdicts = [e for e in events if e["type"] == "oracle_verdict" and e.get("mode") == "grade"]
    if require_signature:
        verdicts = [v for v in verdicts if v.get("signature")]
    if start is None or end is None or not verdicts:
        return None
    return {
        "session_id": start["session_id"],
        "task_id": start.get("task_id"),
        "base_commit": start.get("base_commit"),
        "model": start.get("model"),
        "outcome": end.get("outcome"),
        "attempts": end.get("attempts"),
        "final_verdict": verdicts[-1]["verdict"],
        "tests_hash": verdicts[-1].get("tests_hash"),
        "image_digest": verdicts[-1].get("image_digest"),
        "turns": to_chat(events),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--traces", required=True, help="directory of <session_id>.jsonl trace files")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--require-signature", action="store_true", help="exclude verdicts without a signature")
    args = parser.parse_args()

    traces = Path(args.traces)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    sessions: list[dict[str, Any]] = []
    skipped = 0
    for path in sorted(traces.glob("*.jsonl")):
        summary = summarize(load_session(path), args.require_signature)
        if summary is None:
            skipped += 1
            continue
        sessions.append(summary)

    flipped = [s for s in sessions if s["outcome"] == "flipped" and s["final_verdict"] == "PASS"]
    with (out / "sft.jsonl").open("w", encoding="utf-8") as handle:
        for session in flipped:
            handle.write(json.dumps(session, ensure_ascii=False) + "\n")

    by_task: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"chosen": [], "rejected": []})
    for session in sessions:
        if not session["task_id"]:
            continue
        bucket = "chosen" if session["outcome"] == "flipped" else "rejected"
        by_task[session["task_id"]][bucket].append(session)
    pairs = 0
    with (out / "pairs.jsonl").open("w", encoding="utf-8") as handle:
        for task_id, groups in sorted(by_task.items()):
            for chosen in groups["chosen"]:
                for rejected in groups["rejected"]:
                    handle.write(json.dumps({"task_id": task_id, "chosen": chosen, "rejected": rejected}, ensure_ascii=False) + "\n")
                    pairs += 1

    sys.stderr.write(f"{len(sessions)} sessions read, {skipped} skipped, {len(flipped)} flipped, {pairs} pairs\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
