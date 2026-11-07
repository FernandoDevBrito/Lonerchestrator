#!/usr/bin/env bash
# lonerchestrator installer for macOS / Linux (also works in Git Bash on Windows)
#
#   curl -fsSL https://raw.githubusercontent.com/FernandoDevBrito/lonerchestrator/main/install.sh | bash
#
# Options. As arguments:  bash install.sh [--dry-run] [--uninstall] [--dev] [--ref v0.1.0] [--manager uv|pipx|pip] [--no-path] [--source <path-or-url>] [--with claude,agy]
# Through a pipe pass them after "-s --":  curl -fsSL .../install.sh | bash -s -- --ref v0.1.0
# Or as environment variables: LONERCHESTRATOR_DRYRUN=1, _REF, _MANAGER, _NO_PATH=1, _SOURCE, _WITH.
#
# After installing, it shows which AI CLIs you have (Claude Code, Antigravity) and offers to install the missing ones.
# --with claude,agy installs them without asking (you chose them on purpose); otherwise it asks, showing each official command first.
#
# It uses uv if you have it (uv can even fetch Python for you), else pipx, else pip --user.
# It never installs other programs, never uses sudo, and --dry-run shows every command without running it.
set -euo pipefail

REPO="https://github.com/FernandoDevBrito/lonerchestrator"
PACKAGE="git+${REPO}"          # becomes "lonerchestrator" once the first release is on PyPI

dry="${LONERCHESTRATOR_DRYRUN:-0}"; uninstall=0; dev=0; nopath="${LONERCHESTRATOR_NO_PATH:-0}"
ref="${LONERCHESTRATOR_REF:-}"; source_="${LONERCHESTRATOR_SOURCE:-}"; manager="${LONERCHESTRATOR_MANAGER:-}"; with="${LONERCHESTRATOR_WITH:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1 ;;
    --uninstall) uninstall=1 ;;
    --dev) dev=1 ;;
    --no-path) nopath=1 ;;
    --ref) ref="${2:?--ref needs a value}"; shift ;;
    --source) source_="${2:?--source needs a value}"; shift ;;
    --manager) manager="${2:?--manager needs a value}"; shift ;;
    --with) with="${2:?--with needs a value}"; shift ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
  shift
done

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; D=$'\033[90m'; Z=$'\033[0m'; else G=; Y=; R=; C=; D=; Z=; fi
ok()   { printf '  %s[ ok ]%s %s\n' "$G" "$Z" "$1"; }
warn() { printf '  %s[ !! ]%s %s\n' "$Y" "$Z" "$1"; }
bad()  { printf '  %s[ xx ]%s %s\n' "$R" "$Z" "$1"; }
info() { printf '         %s%s%s\n' "$D" "$1" "$Z"; }
has()  { command -v "$1" >/dev/null 2>&1; }
run()  { if [ "$dry" = 1 ]; then printf '  %s[dry ]%s %s\n' "$C" "$Z" "$*"; else "$@"; fi; }

printf '\n  %slonerchestrator%s  %sinstaller%s' "$C" "$Z" "$D" "$Z"
[ "$dry" = 1 ] && printf '   %s(dry run: nothing will change)%s' "$Y" "$Z"
printf '\n\n'

# ---- which tool installs it
if [ -n "$manager" ]; then
  case "$manager" in uv|pipx|pip) ;; *) echo "--manager must be uv, pipx or pip"; exit 2 ;; esac
  mgr="$manager"; if [ "$mgr" != pip ] && ! has "$mgr"; then bad "$mgr was asked for but is not installed"; exit 1; fi
elif has uv; then mgr=uv; elif has pipx; then mgr=pipx; else mgr=pip; fi
# the first python that really runs and is 3.10+ (on Windows `python3` is often a Microsoft Store stub that only prints an error)
py=""
for cand in python3 python; do
  if has "$cand" && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then py="$(command -v "$cand")"; break; fi
done

# ---- remove
if [ "$uninstall" = 1 ]; then
  found=0
  if   [ "$mgr" = uv ]   && uv tool list 2>/dev/null | grep -q '^lonerchestrator'; then run uv tool uninstall lonerchestrator; found=1
  elif [ "$mgr" = pipx ] && pipx list --short 2>/dev/null | grep -q '^lonerchestrator'; then run pipx uninstall lonerchestrator; found=1
  elif [ "$mgr" = pip ]  && [ -n "$py" ] && "$py" -m pip show lonerchestrator >/dev/null 2>&1; then run "$py" -m pip uninstall -y lonerchestrator; found=1
  fi
  if [ "$found" = 1 ]; then ok "lonerchestrator removed"; info "Your projects, boards and memory were not touched."; else warn "lonerchestrator is not installed with $mgr"; fi
  echo; exit 0
fi

# ---- what to install
if [ -n "$source_" ]; then spec="$source_"
elif [ "$dev" = 1 ]; then
  if [ -f "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/pyproject.toml" ]; then spec="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  else bad "--dev needs a clone: run ./install.sh --dev from inside the repository folder"; exit 1; fi
else spec="$PACKAGE${ref:+@$ref}"; fi

# ---- requirements for the install itself (Claude Code etc. are checked by `lonerchestrator doctor` at the end)
case "$spec" in git+*) has git || { bad "git is needed to download it"; info "install it (https://git-scm.com) and run this again"; exit 1; }; ok "git found" ;; esac
case "$mgr" in
  uv)   ok "uv found: $(uv --version | cut -d' ' -f1,2)  (fetches Python by itself if needed)" ;;
  pipx) ok "pipx found" ;;
  pip)
    [ -n "$py" ] || { bad "Python 3.10 or newer is needed (or install uv: https://docs.astral.sh/uv/)"; exit 1; }
    ok "python found: $("$py" --version)"
    info "tip: uv (https://docs.astral.sh/uv/) installs tools like this one more cleanly" ;;
esac
info "source: $spec"

# ---- install
echo
edit=(); [ "$dev" = 1 ] && edit=(--editable)
case "$mgr" in
  uv)   run uv tool install --force ${edit[@]+"${edit[@]}"} "$spec" ;;
  pipx) run pipx install --force ${edit[@]+"${edit[@]}"} "$spec" ;;
  pip)  run "$py" -m pip install --user --upgrade ${edit[@]+"${edit[@]}"} "$spec" || { echo; bad "pip refused (an externally-managed Python, PEP 668)"; info "install uv or pipx and run this again"; exit 1; } ;;
esac

# ---- make sure the command is on PATH
case "$mgr" in
  uv)   bin="$(uv tool dir --bin)" ;;
  pipx) bin="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || true)"; bin="${bin:-$HOME/.local/bin}" ;;
  pip)  bin="$("$py" -c "import sysconfig; print(sysconfig.get_path('scripts', sysconfig.get_preferred_scheme('user')))")" ;;
esac
case ":$PATH:" in
  *":$bin:"*) ok "$bin is on PATH" ;;
  *) if [ "$nopath" = 1 ]; then warn "$bin is not on PATH (left alone: --no-path)"
     else
       warn "$bin is not on PATH yet"
       case "$mgr" in uv) run uv tool update-shell ;; pipx) run pipx ensurepath ;; *) info "add this to your shell profile:  export PATH=\"$bin:\$PATH\"" ;; esac
       info "open a new terminal for that to apply"
     fi ;;
esac
export PATH="$bin:$PATH"

# ---- prove it works
echo
if [ "$dry" = 1 ]; then
  ok "dry run finished: nothing was changed"
  if [ -n "$with" ]; then printf '  %s[dry ]%s lonerchestrator ais --install %s --yes\n' "$C" "$Z" "$with"
  else printf '  %s[dry ]%s lonerchestrator ais   (shows your AI CLIs and offers to install the missing ones)\n' "$C" "$Z"; fi
else
  has lonerchestrator || { bad "the command was not created in $bin"; exit 1; }
  ok "$(lonerchestrator --version)"
  if [ -n "$with" ]; then lonerchestrator ais --install "$with" --yes || true
  elif { : </dev/tty; } 2>/dev/null; then lonerchestrator ais </dev/tty || true      # through `curl | bash` stdin is the script: ask on the terminal
  else info "run \`lonerchestrator ais\` to see which AI CLIs you have and install the missing ones"; fi
  lonerchestrator doctor || warn "doctor found something to fix (see above): the install itself is fine"
fi

echo
printf '  %sNext steps%s\n' "$C" "$Z"
echo "    cd your-project            a git repository"
echo "    lonerchestrator init       sets up the board and asks which AIs to use"
echo "    lonerchestrator            opens the panel (tab 6 'Settings' shows what is still missing)"
echo
