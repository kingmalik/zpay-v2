#!/usr/bin/env bash
# Test runner wrapper.
#
# No args: run every backend test file in its OWN pytest process.
#   The combined single-process run has known cross-file contamination
#   (module-level app.dependency_overrides leak between files), so per-file
#   isolation is the mode where red = a real failure. Exit 1 if any file fails.
# With args: passthrough to pytest (e.g. ./run_tests.sh backend/tests/test_x.py).
set -uo pipefail
cd "$(dirname "$0")"

if [ "$#" -gt 0 ]; then
  PYTHONPATH=. exec python3 -m pytest "$@"
fi

failed=()
for f in backend/tests/test_*.py; do
  if ! PYTHONPATH=. python3 -m pytest "$f" -q --no-header -p no:cacheprovider >/dev/null 2>&1; then
    failed+=("$f")
    echo "FAIL $f"
  else
    echo "ok   $f"
  fi
done

if [ "${#failed[@]}" -gt 0 ]; then
  echo ""
  echo "${#failed[@]} test file(s) failed — rerun each with: ./run_tests.sh <file> -q"
  exit 1
fi
echo ""
echo "All test files green (per-file isolation)."
