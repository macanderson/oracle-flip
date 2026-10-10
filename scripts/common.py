"""Shared helpers for the oracle-flip hooks.

Every hook reads one JSON event from stdin, writes trace events to the plugin's
data directory, and never prints anything the agent could read except the
Stop hook's fixed decision. Only the standard library is used so the plugin
runs wherever python3 runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
HARNESS = "claude-code"
MAX_CONTENT_BYTES = 64_000
DEFAULT_MAX_ATTEMPTS = 6
DEFAULT_ORACLE_TIMEOUT_SECONDS = 540
CONFIG_PATH = Path(".oracle-flip") / "config.json"

# The Stop hook's reason never changes and never carries oracle output.
BLOCK_REASON_FAIL = "The oracle reports FAIL. The work is not complete. Keep working. The oracle does not say why."
BLOCK_REASON_ERROR = "The oracle could not grade the change. Keep working and try to finish again."


def log(message: str) -> None:
    """Writes a line to stderr. Hooks that exit 0 do not show stderr to the agent."""
    sys.stderr.write(f"oracle-flip: {message}\n")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(value: str | bytes) -> str:
    data = value.encode("utf-8", errors="replace") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def data_dir() -> Path:
    """The plugin's data directory. Survives plugin updates and is not in the repository."""
    root = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or Path.home() / ".oracle-flip")
    for sub in ("traces", "state", "diffs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def read_event() -> dict[str, Any] | None:
    """Parses the hook event from stdin. Returns None, after logging, when the input is not an object."""
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as error:
        log(f"could not parse hook input: {error}")
        return None
    if not isinstance(event, dict) or not isinstance(event.get("session_id"), str):
        log("hook input has no session_id")
        return None
    return event


# ---------------------------------------------------------------------------
# Redaction. A floor, not a guarantee: run a dedicated scanner before training.

_ASSIGNMENT_KEYS = r"(?:SECRET|TOKEN|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY|CLIENT[_-]?SECRET|ACCESS[_-]?KEY)"

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "[REDACTED private key]"),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED aws key]"),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "[REDACTED github token]"),
    ("github-fine-grained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b"), "[REDACTED github token]"),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED slack token]"),
    ("sk-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED api key]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED jwt]"),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"), "Bearer [REDACTED]"),
    ("url-credentials", re.compile(r"://[^/\s:@]+:[^/\s@]+@"), "://[REDACTED]@"),
    (
        "assignment",
        re.compile(rf"(?i)\b([A-Z0-9_]*{_ASSIGNMENT_KEYS}[A-Z0-9_]*)(\s*[=:]\s*)(['\"]?)([^\s'\"]{{6,}})"),
        r"\1\2\3[REDACTED]",
    ),
)


def redact(text: str) -> tuple[str, int]:
    """Replaces secret-shaped substrings. Returns the text and how many replacements were made."""
    count = 0
    for _name, pattern, replacement in SECRET_PATTERNS:
        text, n = pattern.subn(replacement, text)
        count += n
    return text, count


def truncate(text: str, limit: int = MAX_CONTENT_BYTES) -> tuple[str, bool]:
    data = text.encode("utf-8", errors="replace")
    if len(data) <= limit:
        return text, False
    cut = data[:limit].decode("utf-8", errors="ignore")
    return f"{cut}\n[truncated {len(data) - limit} bytes]", True


def content_fields(prefix: str, value: Any) -> dict[str, Any]:
    """The redacted, truncated form of a value plus the hash of the original."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    redacted, redactions = redact(text)
    shown, truncated = truncate(redacted)
    return {
        f"{prefix}_redacted": shown,
        f"{prefix}_hash": sha256(text),
        f"{prefix}_redactions": redactions,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Trace events

def write_event(session_id: str, event_type: str, **fields: Any) -> None:
    record = {"v": SCHEMA_VERSION, "session_id": session_id, "ts": now(), "type": event_type, **fields}
    path = data_dir() / "traces" / f"{session_id}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Per-session state. Written at SessionStart from the project config and never
# re-read from the project afterwards, so edits the agent makes to the config
# during the session do not reach the gate.

@dataclass
class SessionState:
    session_id: str
    task_id: str | None = None
    base_commit: str | None = None
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    oracle_command: list[str] = field(default_factory=list)
    oracle_timeout_seconds: int = DEFAULT_ORACLE_TIMEOUT_SECONDS
    remote_url_hash: str | None = None
    turn: int = 0
    attempts: int = 0
    baseline: str | None = None  # PASS | FAIL | ERROR
    outcome: str | None = None  # flipped | no_flip | no_task | oracle_error | aborted


def state_path(session_id: str) -> Path:
    return data_dir() / "state" / f"{session_id}.json"


def load_state(session_id: str) -> SessionState:
    path = state_path(session_id)
    if not path.exists():
        return SessionState(session_id=session_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    known = {k: v for k, v in data.items() if k in SessionState.__dataclass_fields__}
    return SessionState(**known)


def save_state(state: SessionState) -> None:
    state_path(state.session_id).write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Project configuration, read once at SessionStart.

class ConfigError(ValueError):
    """The project's .oracle-flip/config.json is present but not usable."""


def load_config(cwd: str) -> dict[str, Any] | None:
    """Parses the project config. Returns None when the project has none, so the plugin only traces."""
    path = Path(cwd) / CONFIG_PATH
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must hold a JSON object")
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", task_id):
        raise ConfigError(f"{path}: task_id must be 1 to 128 letters, digits, dots, underscores or dashes")
    base_commit = data.get("base_commit")
    if base_commit is not None and not (isinstance(base_commit, str) and re.fullmatch(r"[0-9a-f]{7,64}", base_commit)):
        raise ConfigError(f"{path}: base_commit must be a hex commit id or null")
    max_attempts = data.get("max_attempts", DEFAULT_MAX_ATTEMPTS)
    if not isinstance(max_attempts, int) or not 1 <= max_attempts <= 50:
        raise ConfigError(f"{path}: max_attempts must be an integer from 1 to 50")
    return {"task_id": task_id, "base_commit": base_commit, "max_attempts": max_attempts}


def oracle_command_from_env() -> list[str]:
    """The oracle command comes from the plugin's user settings, never from the repository."""
    configured = os.environ.get("CLAUDE_PLUGIN_OPTION_ORACLE_COMMAND", "").strip()
    if configured:
        return configured.split()
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not root:
        return []
    return ["bash", str(Path(root) / "oracle" / "run.sh")]


# ---------------------------------------------------------------------------
# Git

def git(cwd: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check, timeout=60)


def git_head(cwd: str) -> str | None:
    try:
        return git(cwd, "rev-parse", "HEAD").stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as error:
        log(f"could not read HEAD: {error}")
        return None


def git_remote_url_hash(cwd: str) -> str | None:
    try:
        url = git(cwd, "remote", "get-url", "origin").stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return sha256(url) if url else None


def write_diff(cwd: str, base_commit: str, out_path: Path) -> str:
    """Writes the working tree's diff against the base commit, including new files. Returns its hash."""
    tracked = git(cwd, "diff", "--binary", base_commit).stdout
    parts = [tracked]
    untracked = git(cwd, "ls-files", "--others", "--exclude-standard", "-z").stdout
    for name in filter(None, untracked.split("\0")):
        # git diff --no-index exits 1 when the files differ, which is the expected case here.
        result = git(cwd, "diff", "--no-index", "--binary", "--", "/dev/null", name, check=False)
        if result.returncode not in (0, 1):
            raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
        parts.append(result.stdout)
    diff = "".join(parts)
    out_path.write_text(diff, encoding="utf-8")
    return sha256(diff)


# ---------------------------------------------------------------------------
# The oracle

@dataclass
class Verdict:
    verdict: str  # PASS | FAIL | ERROR
    tests_hash: str | None = None
    image_digest: str | None = None
    duration_ms: int = 0
    error: str | None = None


def run_oracle(
    command: list[str],
    *,
    mode: str,
    task_id: str,
    base_commit: str,
    diff_path: Path | None,
    remote_url_hash: str | None,
    timeout_seconds: int,
) -> Verdict:
    """Runs the oracle command and reads back one bit. Its output is never shown to the agent."""
    if not command:
        return Verdict("ERROR", error="no oracle command configured")
    env = {
        **os.environ,
        "ORACLE_MODE": mode,
        "ORACLE_TASK_ID": task_id,
        "ORACLE_BASE_COMMIT": base_commit,
        "ORACLE_DIFF": str(diff_path) if diff_path else "",
        "ORACLE_REPO_URL_HASH": remote_url_hash or "",
    }
    started = datetime.now(timezone.utc)
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        return Verdict("ERROR", error=f"oracle exceeded {timeout_seconds}s")
    except OSError as error:
        return Verdict("ERROR", error=f"could not start oracle: {error}")
    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    tests_hash = fields.get("tests_hash")
    image_digest = fields.get("image_digest")
    if result.returncode == 0:
        return Verdict("PASS", tests_hash, image_digest, duration_ms)
    if result.returncode == 1:
        return Verdict("FAIL", tests_hash, image_digest, duration_ms)
    # Anything else is the oracle failing to grade, not the change failing. The
    # stderr stays on this side; only a short code goes into the trace.
    return Verdict("ERROR", tests_hash, image_digest, duration_ms, error=f"oracle exit {result.returncode}")
