#!/usr/bin/env bash
# The hidden tests. Must fail at baseline and pass after a correct change.
set -euo pipefail
python3 -m pytest -q -p no:cacheprovider tests/hidden
