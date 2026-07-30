#!/usr/bin/env bash
# Prepare a reviewed public release candidate without mutating remote state.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

usage() {
  cat <<'EOF'
usage:
  scripts/release.sh check VERSION
  scripts/release.sh prepare VERSION
  scripts/release.sh attest VERSION MERGE_COMMIT

check    Validate the current public main and proposed version without writes.
prepare Create a local release/vVERSION branch, update the version, lockfile,
        and changelog, verify the candidate commit, and build candidate
        artifacts. It does not push, tag, or create a GitHub release.
attest   On the expected merged public main commit, recheck unpublished state
        and the complete lockfile, then build retained, smoke-tested release
        artifacts and hashes.
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

project_version() {
  uv run --frozen python - "$1" <<'PY'
import sys
import tomllib
from pathlib import Path

with Path(sys.argv[1]).open("rb") as handle:
    print(tomllib.load(handle)["project"]["version"])
PY
}

lock_version() {
  uv run --frozen python - "$1" <<'PY'
import sys
import tomllib
from pathlib import Path

with Path(sys.argv[1]).open("rb") as handle:
    packages = tomllib.load(handle)["package"]
root = next(package for package in packages if package["name"] == "lazy-hsa")
print(root["version"])
PY
}

require_semver() {
  [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
    die "version must be MAJOR.MINOR.PATCH (got: $1)"
}

require_versions_match() {
  local project lock
  project="$(project_version pyproject.toml)"
  lock="$(lock_version uv.lock)"
  [[ "$project" == "$lock" ]] ||
    die "project version $project does not match lock root version $lock"
}

require_newer_version() {
  local requested="$1"
  local current
  current="$(project_version pyproject.toml)"
  uv run --frozen python - "$requested" "$current" <<'PY'
import sys

requested = tuple(map(int, sys.argv[1].split(".")))
current = tuple(map(int, sys.argv[2].split(".")))
if requested <= current:
    raise SystemExit(
        f"error: requested version {sys.argv[1]} must be newer than {sys.argv[2]}"
    )
PY
}

require_nonempty_changelog() {
  uv run --frozen python - <<'PY'
import re
from pathlib import Path

text = Path("CHANGELOG.md").read_text(encoding="utf-8")
match = re.search(
    r"^## \[Unreleased\]\s*$\n(?P<body>.*?)(?=^## \[|\Z)",
    text,
    flags=re.MULTILINE | re.DOTALL,
)
if match is None or not match.group("body").strip():
    raise SystemExit("error: CHANGELOG.md [Unreleased] section is empty")
PY
}

require_unpublished_version() {
  local version="$1"
  [[ -z "$(git ls-remote --tags origin "refs/tags/v$version")" ]] ||
    die "remote tag v$version already exists"
  ! git rev-parse --verify "refs/tags/v$version" >/dev/null 2>&1 ||
    die "local tag v$version already exists"
  [[ "$(gh release list --repo minghsuy/lazy-hsa --limit 1000 \
    --json tagName --jq "any(.[]; .tagName == \"v$version\")")" == "false" ]] ||
    die "GitHub release v$version already exists"
}

preflight() {
  local version="$1"
  require_semver "$version"
  [[ -z "$(git status --porcelain)" ]] || die "working tree is dirty"
  [[ "$(git rev-parse --abbrev-ref HEAD)" == "main" ]] ||
    die "must run from main"
  git fetch origin main
  [[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] ||
    die "local main is not the exact public remote head"
  require_versions_match
  uv lock --check
  require_newer_version "$version"
  require_nonempty_changelog
  require_unpublished_version "$version"
}

bump_changelog() {
  local version="$1"
  local today
  today="$(date -u +%Y-%m-%d)"
  uv run --frozen python - "$version" "$today" <<'PY'
import re
import sys
from pathlib import Path

version, today = sys.argv[1:]
path = Path("CHANGELOG.md")
text = path.read_text(encoding="utf-8")
updated, count = re.subn(
    r"^## \[Unreleased\]$",
    f"## [Unreleased]\n\n## [{version}] - {today}",
    text,
    count=1,
    flags=re.MULTILINE,
)
if count != 1:
    raise SystemExit("CHANGELOG.md must contain exactly one [Unreleased] heading")
path.write_text(updated, encoding="utf-8")
PY
}

prepare() {
  local version="$1"
  preflight "$version"
  git switch -c "release/v$version"
  uv version "$version"
  bump_changelog "$version"
  require_versions_match
  uv lock --check
  git add pyproject.toml uv.lock CHANGELOG.md
  git commit -m "Release v$version"

  # The complete distribution gate runs after the release commit exists.
  scripts/verify.sh --verbose

  local commit artifact_dir
  commit="$(git rev-parse HEAD)"
  artifact_dir="$REPO_DIR/dist/candidate-v$version"
  mkdir -p "$artifact_dir"
  [[ -z "$(find "$artifact_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]] ||
    die "artifact directory is not empty: $artifact_dir"
  scripts/verify-dist.sh "$artifact_dir"
  printf '%s\n' "$commit" >"$artifact_dir/RELEASE-COMMIT"
  (
    cd "$artifact_dir"
    sha256sum lazy_hsa-* >SHA256SUMS
  )

  echo "prepared v$version at $commit"
  echo "candidate artifacts: $artifact_dir"
  echo "next: push the branch and open a PR for independent review"
  echo "after merge, run: scripts/release.sh attest $version MERGE_COMMIT"
  echo "nothing was tagged or published"
}

attest() {
  local version="$1"
  local expected_commit="$2"
  require_semver "$version"
  [[ "$expected_commit" =~ ^[0-9a-f]{40}$ ]] ||
    die "MERGE_COMMIT must be a full 40-character commit SHA"
  [[ -z "$(git status --porcelain)" ]] || die "working tree is dirty"
  [[ "$(git rev-parse --abbrev-ref HEAD)" == "main" ]] ||
    die "must attest from main"
  git fetch origin main
  [[ "$(git rev-parse HEAD)" == "$expected_commit" ]] ||
    die "HEAD is not the expected release PR merge commit"
  [[ "$(git rev-parse origin/main)" == "$expected_commit" ]] ||
    die "public remote main is not the expected release PR merge commit"
  require_versions_match
  [[ "$(project_version pyproject.toml)" == "$version" ]] ||
    die "project version does not match v$version"
  uv lock --check
  require_unpublished_version "$version"

  scripts/verify.sh --verbose

  local commit artifact_dir
  commit="$expected_commit"
  artifact_dir="$REPO_DIR/dist/release-v$version"
  mkdir -p "$artifact_dir"
  [[ -z "$(find "$artifact_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]] ||
    die "artifact directory is not empty: $artifact_dir"
  scripts/verify-dist.sh "$artifact_dir"
  printf '%s\n' "$commit" >"$artifact_dir/RELEASE-COMMIT"
  (
    cd "$artifact_dir"
    sha256sum lazy_hsa-* >SHA256SUMS
  )

  # Verification can take long enough for remote state to change. Recheck the
  # exact merge pin and all release namespaces immediately before success.
  git fetch origin main
  [[ "$(git rev-parse HEAD)" == "$expected_commit" ]] ||
    die "HEAD changed during release attestation"
  [[ "$(git rev-parse origin/main)" == "$expected_commit" ]] ||
    die "public remote main changed during release attestation"
  require_unpublished_version "$version"
  git diff --quiet && git diff --cached --quiet ||
    die "tracked files changed during release attestation"

  echo "attested v$version at exact public main $commit"
  echo "release artifacts: $artifact_dir"
  echo "nothing was tagged or published"
}

case "${1:-}" in
  -h | --help | help)
    usage
    ;;
  check)
    [[ $# == 2 ]] || { usage >&2; exit 2; }
    preflight "$2"
    echo "release preflight passed for v$2; no state changed"
    ;;
  prepare)
    [[ $# == 2 ]] || { usage >&2; exit 2; }
    prepare "$2"
    ;;
  attest)
    [[ $# == 3 ]] || { usage >&2; exit 2; }
    attest "$2" "$3"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
