#!/usr/bin/env bash
# Pre-commit / pre-PR verification gate.
# Replaces inference-time "did you verify?" prose with a deterministic command.
#
# Exits non-zero on any failure. Use --verbose for step labels and a final
# success line; otherwise output is just whatever ruff/pytest print themselves.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

VERBOSE=0
[[ "${1:-}" == "--verbose" || "${1:-}" == "-v" ]] && VERBOSE=1

step() {
  if (( VERBOSE )); then
    echo "==> $*"
  fi
}

step "ruff check"
uv run ruff check src/ tests/

step "ruff format --check"
uv run ruff format --check src/ tests/

step "pytest"
uv run pytest -q

# Record successful verification for the PrePush gate hook.
# ~/.claude/hooks/require-verify.py reads this to confirm HEAD has been verified
# before allowing `git push`. Marker is per-repo (lives in .git/config) and
# auto-invalidates on every new commit (since SHA changes).
git config --local hooks.last-verify-sha "$(git rev-parse HEAD)"

if (( VERBOSE )); then
  echo "ok: lint + format + tests pass (recorded for $(git rev-parse --short HEAD))"
fi
