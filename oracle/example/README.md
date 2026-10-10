# Example task

One task for the oracle store: `billing-proration-rounding`. Copy this directory into your oracle store under the task id, point the store at a mirror of the repository, and set `.oracle-flip/config.json` in the agent's checkout to:

```json
{ "task_id": "billing-proration-rounding", "base_commit": null, "max_attempts": 6 }
```

The files:

| File | Purpose |
|---|---|
| `allowlist` | Globs of paths the agent's diff may change |
| `denylist` | Globs the diff may never change, even inside the allowlist |
| `tests.txt` | Identifiers of the hidden tests; the oracle reports a hash of this list |
| `hidden/` | Files copied into the checkout after the diff is applied. Here, one test file. |
| `run_suite.sh` | Runs the existing suite. Exit 0 when it passes. |
| `run_hidden.sh` | Runs the hidden tests. Exit 0 when they pass. |

Before you dispatch the task, run the oracle in baseline mode. It must exit 1 (the hidden tests fail, the suite passes). If it exits 0 the hidden test already passes and there is no task. If it exits 2 the base commit is broken.
