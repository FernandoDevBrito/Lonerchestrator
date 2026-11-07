#!/usr/bin/env bash
# Install lonerchestrator on macOS / Linux.
#   ./install.sh              install (editable: `git pull` updates the command)
#   ./install.sh --dry-run    show what it would do, change nothing
#   ./install.sh --uninstall  remove the package
# Touches nothing outside Python (no shell profile edits): it only tells you if the command is not on PATH.
set -euo pipefail
repo="$(cd "$(dirname "$0")" && pwd)"
dry=0; uninstall=0
for a in "$@"; do
  case "$a" in
    --dry-run) dry=1 ;;
    --uninstall) uninstall=1 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
done
step() { printf '\033[36m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$1"; }
run()  { if [ "$dry" = 1 ]; then echo "  [dry-run] $*"; else "$@"; fi; }

step "Requirements"
py="$(command -v python3 || command -v python || true)"
[ -n "$py" ] || { echo "Python not found. Install Python 3.10+ and run again."; exit 1; }
"$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "Python 3.10 or newer is required."; exit 1; }
echo "  python  $("$py" --version)"
command -v git >/dev/null || { echo "git not found."; exit 1; }
echo "  git     ok"
command -v claude >/dev/null && echo "  claude  ok" || warn "claude not found. Install Claude Code: https://claude.com/claude-code"
command -v agy    >/dev/null && echo "  agy     ok" || warn "agy not found (optional, Gemini reviewer): https://antigravity.google"
command -v bash   >/dev/null && echo "  bash    ok"

if [ "$uninstall" = 1 ]; then
  step "Removing"
  if command -v pipx >/dev/null && pipx list 2>/dev/null | grep -q lonerchestrator; then run pipx uninstall lonerchestrator
  else run "$py" -m pip uninstall -y lonerchestrator; fi
  echo "Done. (Your projects, boards and memory were not touched.)"
  exit 0
fi

step "Installing (editable) from $repo"
if command -v pipx >/dev/null; then
  run pipx install --force --editable "$repo"
else
  # newer distros mark system Python "externally managed" (PEP 668): then install pipx or use a venv
  run "$py" -m pip install --user --upgrade --editable "$repo" || {
    echo "pip refused (externally-managed Python). Install pipx (e.g. 'brew install pipx' or 'sudo apt install pipx') and run again."; exit 1; }
fi

step "Checking the command"
if [ "$dry" = 0 ]; then
  if command -v lonerchestrator >/dev/null; then echo "  $(command -v lonerchestrator)"
  else warn "installed, but 'lonerchestrator' is not on PATH yet. Add ~/.local/bin to PATH (pipx ensurepath) and open a new terminal."; fi
fi

echo
printf '\033[32mDone. In a NEW terminal:\033[0m\n'
echo "  cd your-project"
echo "  lonerchestrator init     # set up board, agents, guardrails + introduction"
echo "  lonerchestrator          # open the panel"
