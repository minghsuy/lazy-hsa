#!/usr/bin/env bash
# Dual-repo release: hsa-receipt-system (private) + lazy-hsa (public mirror).
# Encodes the workflow previously stored as a memory note.
#
# Usage: scripts/release.sh <new-version>     e.g. scripts/release.sh 1.5.0
#        scripts/release.sh --check           dry run, no writes
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

DRY_RUN=0
if [[ "${1:-}" == "--check" ]]; then
  DRY_RUN=1
  shift || true
fi

NEW_VERSION="${1:-}"
if [[ -z "$NEW_VERSION" ]]; then
  echo "usage: scripts/release.sh [--check] <new-version>" >&2
  echo "current: $(grep '^version' pyproject.toml | head -1)" >&2
  exit 2
fi

if [[ ! "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "error: version must be MAJOR.MINOR.PATCH (got: $NEW_VERSION)" >&2
  exit 2
fi

run() {
  if (( DRY_RUN )); then
    echo "+ $*"
  else
    echo "+ $*"
    "$@"
  fi
}

# --- Pre-flight gates ---
if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: working tree dirty — commit or stash first" >&2
  git status --short
  exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "error: must release from main (current: $CURRENT_BRANCH)" >&2
  exit 1
fi

# Always fetch (read-only) so the sync check uses fresh refs even in --check mode.
git fetch origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [[ "$LOCAL" != "$REMOTE" ]]; then
  echo "error: local main not in sync with origin/main" >&2
  exit 1
fi

if git rev-parse "v${NEW_VERSION}" >/dev/null 2>&1; then
  echo "error: tag v${NEW_VERSION} already exists" >&2
  exit 1
fi

# --- Quality gates ---
echo "==> running verify"
run "$REPO_DIR/scripts/verify.sh"

# --- Sync wiki repo (read-only pre-flight) ---
# wiki-repo/ is a SEPARATE git repo tracking lazy-hsa.wiki.git. We don't
# auto-write to it (page content is curated per release), but we do want to
# fail fast if its working tree is dirty — otherwise the user has un-published
# wiki edits hanging around at release time.
echo "==> checking wiki"
if [[ -d "$REPO_DIR/wiki-repo" ]]; then
  if [[ -n "$(git -C "$REPO_DIR/wiki-repo" status --porcelain 2>/dev/null)" ]]; then
    echo "error: wiki-repo has uncommitted changes — commit or stash before release" >&2
    git -C "$REPO_DIR/wiki-repo" status --short
    exit 1
  fi
  run git -C "$REPO_DIR/wiki-repo" pull --ff-only
else
  echo "warn: wiki-repo not present at $REPO_DIR/wiki-repo — skipping wiki sync"
fi

# --- Bump version ---
echo "==> bumping version to $NEW_VERSION"
if (( DRY_RUN )); then
  echo "+ would set version = \"$NEW_VERSION\" in pyproject.toml"
else
  python -c "
import re, pathlib
p = pathlib.Path('pyproject.toml')
t = p.read_text()
t = re.sub(r'^version = \".*\"', 'version = \"$NEW_VERSION\"', t, count=1, flags=re.M)
p.write_text(t)
"
  run git add pyproject.toml
  run git commit -m "Release v${NEW_VERSION}"
fi

# --- Bump CHANGELOG.md ---
# Move the [Unreleased] section to a versioned heading and reinsert an empty
# [Unreleased] for the next cycle. Amend into the version-bump commit so we
# get one "Release vX.Y.Z" commit, not two. If [Unreleased] is missing (e.g.
# user already bumped manually), warn and skip rather than fail.
echo "==> bumping CHANGELOG"
TODAY=$(date -u +%Y-%m-%d)
if [[ ! -f CHANGELOG.md ]]; then
  echo "warn: CHANGELOG.md not present — skipping bump"
elif ! grep -q '^## \[Unreleased\]' CHANGELOG.md; then
  echo "warn: no [Unreleased] section in CHANGELOG.md — skipping bump"
elif (( DRY_RUN )); then
  echo "+ would bump CHANGELOG.md: [Unreleased] -> [$NEW_VERSION] - $TODAY (and reinsert empty [Unreleased])"
else
  python -c "
import re, pathlib
p = pathlib.Path('CHANGELOG.md')
text = p.read_text()
# Match the bare heading line (no trailing-whitespace consume) so the original
# newline + blank line between sections is preserved as the separator after
# the new versioned heading we're inserting.
new = re.sub(
    r'^## \[Unreleased\]$',
    '## [Unreleased]\n\n## [$NEW_VERSION] - $TODAY',
    text, count=1, flags=re.M)
p.write_text(new)
"
  run git add CHANGELOG.md
  run git commit --amend --no-edit
fi

# --- Tag and push ---
run git tag -a "v${NEW_VERSION}" -m "v${NEW_VERSION}"
run git push origin main
run git push origin "v${NEW_VERSION}"
run git push lazy-hsa main
run git push lazy-hsa "v${NEW_VERSION}"

# --- GitHub releases on both remotes ---
# Skip notes generation in dry-run: the tag doesn't exist yet so `git describe`
# would silently produce misleading "Initial release." output.
if (( DRY_RUN )); then
  echo "+ would generate release notes from git log and create GitHub releases on both remotes"
  echo
  echo "==> dry run complete"
  exit 0
fi

NOTES_FILE=$(mktemp)
trap 'rm -f "$NOTES_FILE"' EXIT
{
  echo "## What's changed in v${NEW_VERSION}"
  echo
  PREV_TAG=$(git describe --tags --abbrev=0 "v${NEW_VERSION}^" 2>/dev/null || echo "")
  if [[ -n "$PREV_TAG" ]]; then
    git log "$PREV_TAG..v${NEW_VERSION}" --pretty="format:- %s" --no-merges
  else
    echo "Initial release."
  fi
} > "$NOTES_FILE"

run gh release create "v${NEW_VERSION}" \
  --repo minghsuy/hsa-receipt-system \
  --title "v${NEW_VERSION}" \
  --notes-file "$NOTES_FILE"

run gh release create "v${NEW_VERSION}" \
  --repo minghsuy/lazy-hsa \
  --title "v${NEW_VERSION}" \
  --notes-file "$NOTES_FILE"

echo
echo "==> released v${NEW_VERSION} to both repos"
echo "    https://github.com/minghsuy/hsa-receipt-system/releases/tag/v${NEW_VERSION}"
echo "    https://github.com/minghsuy/lazy-hsa/releases/tag/v${NEW_VERSION}"
