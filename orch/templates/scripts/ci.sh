#!/usr/bin/env bash
# CI gate for this project: lint, tests, build. Exit non-zero on any failure. Edit to fit the stack.
set -u
cd "$(dirname "$0")/.."
fail=0
if [ -f pyproject.toml ] || [ -f requirements.txt ] || ls ./*.py >/dev/null 2>&1; then
  PY=python; [ -x .venv/Scripts/python.exe ] && PY=.venv/Scripts/python; [ -x .venv/bin/python ] && PY=.venv/bin/python
  "$PY" -m ruff check . || fail=1
  "$PY" -m compileall -q -x '(\.git|\.venv|node_modules)' . || fail=1
  "$PY" -m pytest -q; rc=$?; [ $rc -eq 0 ] || [ $rc -eq 5 ] || fail=1   # 5 = no tests yet
elif [ -f package.json ]; then
  npm run -s lint --if-present || fail=1
  npm test --if-present || fail=1
  npm run -s build --if-present || fail=1
else
  echo "CI: no known stack, edit scripts/ci.sh"; fail=1
fi
[ $fail -eq 0 ] && echo "CI: PASS" || echo "CI: FAIL"
exit $fail
