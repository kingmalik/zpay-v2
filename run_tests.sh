#!/usr/bin/env bash
# Test runner wrapper — runs pytest on a module by module path
# Usage: ./run_tests.sh <pytest args>
set -euo pipefail
cd "$(dirname "$0")"
PYTHONPATH=. exec python3 -m pytest "$@"
