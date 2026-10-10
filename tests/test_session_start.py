import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "session_start.py"


def run_hook(event: dict, data_dir: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PLUGIN_DATA": data_dir, "CLAUDE_PLUGIN_ROOT": str(SCRIPT.parents[1])}
    # Run the hook the way the harness does: `python3 <script>`, which puts scripts/ on sys.path for `common`.
    return subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(event), text=True, capture_output=True, env=env, check=True)


def git(cwd: str, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class SessionStartTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.repo = tempfile.TemporaryDirectory()
        git(self.repo.name, "init", "-q", "-b", "main")
        git(self.repo.name, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
        (Path(self.repo.name) / ".oracle-flip").mkdir()
        (Path(self.repo.name) / ".oracle-flip" / "config.json").write_text(json.dumps({"task_id": "t1", "base_commit": None, "max_attempts": 4}))
        (Path(self.repo.name) / "src").mkdir()

    def tearDown(self):
        self.data.cleanup()
        self.repo.cleanup()

    def events(self):
        return [json.loads(l) for l in (Path(self.data.name) / "traces" / "s1.jsonl").read_text().splitlines()]

    def state(self):
        return json.loads((Path(self.data.name) / "state" / "s1.json").read_text())

    def test_snapshots_from_the_repository_root_when_started_in_a_subdirectory(self):
        run_hook({"session_id": "s1", "cwd": str(Path(self.repo.name) / "src"), "hook_event_name": "SessionStart", "source": "startup"}, self.data.name)
        state = self.state()
        self.assertEqual(state["task_id"], "t1")
        self.assertEqual(state["max_attempts"], 4)
        self.assertEqual(state["base_commit"], git(self.repo.name, "rev-parse", "HEAD"))
        self.assertEqual(Path(state["repo_root"]).resolve(), Path(self.repo.name).resolve())
        self.assertTrue(state["started"])

    def test_resume_keeps_the_original_base_commit_and_writes_no_second_start(self):
        run_hook({"session_id": "s1", "cwd": self.repo.name, "hook_event_name": "SessionStart", "source": "startup"}, self.data.name)
        base = self.state()["base_commit"]
        git(self.repo.name, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "agent commit")
        run_hook({"session_id": "s1", "cwd": self.repo.name, "hook_event_name": "SessionStart", "source": "resume"}, self.data.name)
        self.assertEqual(self.state()["base_commit"], base)
        self.assertEqual([e["type"] for e in self.events()], ["session_start"])

    def test_config_error_is_recorded_and_the_session_only_traces(self):
        (Path(self.repo.name) / ".oracle-flip" / "config.json").write_text("{not json")
        run_hook({"session_id": "s1", "cwd": self.repo.name, "hook_event_name": "SessionStart", "source": "startup"}, self.data.name)
        state = self.state()
        self.assertIsNone(state["task_id"])
        self.assertIn("not valid JSON", self.events()[0]["config_error"])


if __name__ == "__main__":
    unittest.main()
