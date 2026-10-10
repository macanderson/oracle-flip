import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from common import BLOCK_REASON_ERROR, BLOCK_REASON_FAIL, SessionState, Verdict  # noqa: E402
from gate import decide  # noqa: E402


def fake_diff(_cwd: str, _base: str, out_path: Path) -> str:
    out_path.write_text("diff --git a/src/x.py b/src/x.py\n", encoding="utf-8")
    return "deadbeef"


class ScriptedOracle:
    """Returns the scripted verdicts in order and records every call."""

    def __init__(self, *verdicts: str):
        self.verdicts = list(verdicts)
        self.calls = []

    def __call__(self, command, *, mode, diff_path, **kwargs):
        self.calls.append(mode)
        return Verdict(self.verdicts.pop(0), tests_hash="abc")


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_PLUGIN_DATA"] = self.tmp.name
        self.event = {"session_id": "s1", "cwd": self.tmp.name, "hook_event_name": "Stop", "last_assistant_message": "Done."}

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("CLAUDE_PLUGIN_DATA", None)

    def state(self, **overrides) -> SessionState:
        base = dict(session_id="s1", task_id="t1", base_commit="abc1234", max_attempts=3, oracle_command=["true"])
        base.update(overrides)
        return SessionState(**base)

    def events(self):
        path = Path(self.tmp.name) / "traces" / "s1.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_blocks_on_fail_with_the_fixed_reason(self):
        oracle = ScriptedOracle("FAIL", "FAIL")
        state = self.state()
        decision = decide(self.event, state, oracle=oracle, diff=fake_diff)
        self.assertEqual(decision, {"decision": "block", "reason": BLOCK_REASON_FAIL})
        self.assertEqual(oracle.calls, ["baseline", "grade"])
        self.assertEqual(state.baseline, "FAIL")
        self.assertEqual(state.attempts, 1)
        self.assertIsNone(state.outcome)
        kinds = [e["type"] for e in self.events()]
        self.assertEqual(kinds, ["message", "oracle_verdict", "oracle_verdict"])

    def test_allows_and_marks_flipped_on_pass(self):
        state = self.state(baseline="FAIL")
        decision = decide(self.event, state, oracle=ScriptedOracle("PASS"), diff=fake_diff)
        self.assertIsNone(decision)
        self.assertEqual(state.outcome, "flipped")
        verdict = [e for e in self.events() if e["type"] == "oracle_verdict"][-1]
        self.assertEqual(verdict["verdict"], "PASS")
        self.assertEqual(verdict["diff_hash"], "deadbeef")

    def test_gives_up_at_max_attempts_as_no_flip(self):
        state = self.state(baseline="FAIL", attempts=2, max_attempts=3)
        decision = decide(self.event, state, oracle=ScriptedOracle("FAIL"), diff=fake_diff)
        self.assertIsNone(decision)
        self.assertEqual(state.outcome, "no_flip")
        self.assertEqual(state.attempts, 3)

    def test_baseline_pass_means_no_task(self):
        oracle = ScriptedOracle("PASS")
        state = self.state()
        decision = decide(self.event, state, oracle=oracle, diff=fake_diff)
        self.assertIsNone(decision)
        self.assertEqual(state.outcome, "no_task")
        self.assertEqual(oracle.calls, ["baseline"])

    def test_baseline_error_ends_without_looping(self):
        state = self.state()
        decision = decide(self.event, state, oracle=ScriptedOracle("ERROR"), diff=fake_diff)
        self.assertIsNone(decision)
        self.assertEqual(state.outcome, "oracle_error")

    def test_oracle_error_during_grade_blocks_with_error_reason(self):
        state = self.state(baseline="FAIL")
        decision = decide(self.event, state, oracle=ScriptedOracle("ERROR"), diff=fake_diff)
        self.assertEqual(decision, {"decision": "block", "reason": BLOCK_REASON_ERROR})

    def test_settled_outcome_never_runs_the_oracle_again(self):
        oracle = ScriptedOracle()
        state = self.state(baseline="FAIL", outcome="flipped")
        self.assertIsNone(decide(self.event, state, oracle=oracle, diff=fake_diff))
        self.assertEqual(oracle.calls, [])

    def test_no_task_configured_only_traces(self):
        oracle = ScriptedOracle()
        state = SessionState(session_id="s1")
        self.assertIsNone(decide(self.event, state, oracle=oracle, diff=fake_diff))
        self.assertEqual(oracle.calls, [])
        self.assertEqual([e["type"] for e in self.events()], ["message"])

    def test_diff_failure_counts_as_an_attempt(self):
        def broken_diff(_cwd, _base, _out):
            raise RuntimeError("git missing")

        state = self.state(baseline="FAIL")
        decision = decide(self.event, state, oracle=ScriptedOracle(), diff=broken_diff)
        self.assertEqual(decision, {"decision": "block", "reason": BLOCK_REASON_ERROR})
        self.assertEqual(state.attempts, 1)

    def test_reason_never_carries_oracle_output(self):
        for reason in (BLOCK_REASON_FAIL, BLOCK_REASON_ERROR):
            self.assertNotIn("test", reason.lower().replace("the oracle", ""))
            self.assertNotIn("assert", reason.lower())

    def test_run_oracle_maps_exit_codes(self):
        pass_v = common.run_oracle(["sh", "-c", "echo tests_hash=h; exit 0"], mode="grade", task_id="t", base_commit="b", diff_path=None, remote_url_hash=None, timeout_seconds=5)
        fail_v = common.run_oracle(["sh", "-c", "exit 1"], mode="grade", task_id="t", base_commit="b", diff_path=None, remote_url_hash=None, timeout_seconds=5)
        err_v = common.run_oracle(["sh", "-c", "echo secret-test-output; exit 3"], mode="grade", task_id="t", base_commit="b", diff_path=None, remote_url_hash=None, timeout_seconds=5)
        self.assertEqual((pass_v.verdict, pass_v.tests_hash), ("PASS", "h"))
        self.assertEqual(fail_v.verdict, "FAIL")
        self.assertEqual(err_v.verdict, "ERROR")
        self.assertNotIn("secret-test-output", err_v.error or "")
        missing = common.run_oracle([], mode="grade", task_id="t", base_commit="b", diff_path=None, remote_url_hash=None, timeout_seconds=5)
        self.assertEqual(missing.verdict, "ERROR")


if __name__ == "__main__":
    unittest.main()
