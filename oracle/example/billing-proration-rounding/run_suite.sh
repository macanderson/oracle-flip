#!/usr/bin/env bash
# The existing suite at the base commit. Must pass before and after the change.
set -euo pipefail
python3 -m pytest -q -p no:cacheprovider --ignore=tests/hidden tests
