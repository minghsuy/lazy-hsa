"""Installed-distribution and public-release contract tests."""

import runpy
import subprocess
from pathlib import Path

import yaml

REPO_DIR = Path(__file__).resolve().parents[1]


def workflow_paths(root: Path) -> list[Path]:
    """Return both supported GitHub Actions workflow extensions."""
    return sorted([*root.glob("*.yml"), *root.glob("*.yaml")])


def executable_uses_refs(workflow: dict) -> list[str]:
    """Return action-step and reusable-workflow executable references."""
    refs: list[str] = []
    for job in workflow.get("jobs", {}).values():
        if "uses" in job:
            refs.append(job["uses"])
        refs.extend(step["uses"] for step in job.get("steps", []) if "uses" in step)
    return refs


def uses_ref_is_immutable(ref: str) -> bool:
    """Accept repository-local actions, image digests, or exact Git SHAs."""
    if ref.startswith("./"):
        return True
    if ref.startswith("docker://"):
        digest = ref.rpartition("@sha256:")[2]
        return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)
    revision = ref.rpartition("@")[2]
    return len(revision) == 40 and all(character in "0123456789abcdef" for character in revision)


def repository_uses_refs(repo_dir: Path) -> list[str]:
    """Return workflow refs plus refs from reachable local composite actions."""
    refs: list[str] = []
    pending_local_refs: list[str] = []
    for workflow_path in workflow_paths(repo_dir / ".github" / "workflows"):
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
        workflow_refs = executable_uses_refs(workflow)
        refs.extend(workflow_refs)
        pending_local_refs.extend(ref for ref in workflow_refs if ref.startswith("./"))

    seen_local_refs: set[str] = set()
    while pending_local_refs:
        local_ref = pending_local_refs.pop()
        if local_ref in seen_local_refs:
            continue
        seen_local_refs.add(local_ref)
        action_dir = (repo_dir / local_ref[2:]).resolve()
        try:
            action_dir.relative_to(repo_dir.resolve())
        except ValueError:
            refs.append("__invalid_local_action__")
            continue
        manifests = [
            path
            for path in (action_dir / "action.yml", action_dir / "action.yaml")
            if path.is_file()
        ]
        if len(manifests) != 1:
            # A local reusable workflow is already represented by its local ref.
            if local_ref.startswith("./.github/workflows/"):
                continue
            refs.append("__invalid_local_action__")
            continue
        action = yaml.safe_load(manifests[0].read_text(encoding="utf-8")) or {}
        nested_refs = [
            step["uses"] for step in action.get("runs", {}).get("steps", []) if "uses" in step
        ]
        refs.extend(nested_refs)
        pending_local_refs.extend(ref for ref in nested_refs if ref.startswith("./"))
    return refs


def test_built_distribution_contract():
    """The wheel must preserve its runtime dependencies and HEIC path."""
    subprocess.run(
        [REPO_DIR / "scripts" / "verify-dist.sh"],
        cwd=REPO_DIR,
        check=True,
    )


def test_public_release_helper_never_publishes():
    """Candidate preparation must not mutate public remote release state."""
    script = (REPO_DIR / "scripts" / "release.sh").read_text(encoding="utf-8")
    assert "git push" not in script
    assert "gh release create" not in script
    result = subprocess.run(
        [REPO_DIR / "scripts" / "release.sh", "--help"],
        cwd=REPO_DIR,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0
    assert "does not push, tag, or create" in result.stdout
    assert "attest VERSION MERGE_COMMIT" in result.stdout
    assert "uv run --frozen python" in script
    assert script.count("git fetch origin main") >= 3
    assert script.count('require_unpublished_version "$version"') >= 3


def test_ci_security_and_tooling_are_fail_closed(tmp_path):
    """Required CI must not suppress findings or execute mutable action refs."""
    mutable_revision = "@" + "main"
    workflow = yaml.safe_load(
        (REPO_DIR / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    security = workflow["jobs"]["security"]
    bandit_steps = [
        step for step in security["steps"] if step.get("name") == "Run bandit security linter"
    ]
    assert len(bandit_steps) == 1
    assert "continue-on-error" not in security
    assert "continue-on-error" not in bandit_steps[0]

    yaml_workflow = tmp_path / "build.yaml"
    yaml_workflow.write_text("jobs: {}\n", encoding="utf-8")
    assert workflow_paths(tmp_path) == [yaml_workflow]
    assert executable_uses_refs(
        {
            "jobs": {
                "reusable": {"uses": "owner/repo/.github/workflows/build.yml" + mutable_revision}
            }
        }
    ) == ["owner/repo/.github/workflows/build.yml" + mutable_revision]
    assert uses_ref_is_immutable("./.github/actions/local")
    assert uses_ref_is_immutable("docker://alpine" + "@sha256:" + ("a" * 64))
    assert not uses_ref_is_immutable("actions/checkout" + mutable_revision)

    action_refs = repository_uses_refs(REPO_DIR)
    assert action_refs
    assert all(uses_ref_is_immutable(ref) for ref in action_refs)

    local_action_dir = tmp_path / ".github" / "actions" / "local"
    local_action_dir.mkdir(parents=True)
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "build.yaml").write_text(
        "jobs:\n  build:\n    steps:\n      - uses: ./.github/actions/local\n",
        encoding="utf-8",
    )
    (local_action_dir / "action.yml").write_text(
        "runs:\n  using: composite\n  steps:\n    - uses: external/action@main\n",
        encoding="utf-8",
    )
    assert not all(uses_ref_is_immutable(ref) for ref in repository_uses_refs(tmp_path))


def test_public_tree_has_no_environment_metadata():
    """The staged public tree must not regain the removed metadata categories."""
    result = subprocess.run(
        [REPO_DIR / "scripts" / "check-public-metadata.py"],
        cwd=REPO_DIR,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_public_metadata_guard_has_bounded_context_free_rules():
    """The guard catches high-signal tokens without interpreting commands."""
    namespace = runpy.run_path(str(REPO_DIR / "scripts" / "check-public-metadata.py"))
    categories = namespace["metadata_categories"]

    endpoint = "user" + "@private-host"
    assert "direct SSH machine endpoint" in categories(endpoint)
    assert "direct SSH machine endpoint" in categories("jump=" + endpoint)
    assert "direct SSH machine endpoint" not in categories("contact user@example.com")
    assert "direct SSH machine endpoint" not in categories("from:auto-confirm@amazon.com")
    assert "direct SSH machine endpoint" not in categories("uses: actions/checkout@v4")
    assert "direct SSH machine endpoint" not in categories("uses: actions/checkout@" + ("a" * 40))
    assert "direct SSH machine endpoint" not in categories(
        "git" + "@github.com:minghsuy/lazy-hsa.git"
    )

    private_contact = "person" + "@private.test"
    assert "non-example email address" in categories(private_contact)
    assert "non-example email address" not in categories("person@example.com")

    for home in (
        "/" + "home/private-user/config",
        "/" + "Users/private-user/config",
        "C:" + "\\Users\\private-user\\config",
        "/" + "root/.ssh/config",
    ):
        assert "absolute user-home path" in categories(home)

    private_repo = "https://github.com/minghsuy/" + "private-infra"
    assert "environment-specific GitHub repository" in categories(private_repo)
    assert "environment-specific GitHub repository" not in categories(
        "https://github.com/minghsuy/lazy-hsa"
    )


def test_public_metadata_guard_scans_exact_index_and_tracked_names(tmp_path):
    """Worktree edits and symlinks cannot hide staged public metadata."""
    namespace = runpy.run_path(str(REPO_DIR / "scripts" / "check-public-metadata.py"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    endpoint = "user" + "@private-host"
    staged_file = repo / "metadata.txt"
    staged_file.write_text(endpoint, encoding="utf-8")
    subprocess.run(["git", "add", "metadata.txt"], cwd=repo, check=True)
    staged_file.write_text("clean worktree", encoding="utf-8")

    link = repo / "published-link"
    link.symlink_to("/" + "home/private-user/config")
    subprocess.run(["git", "add", "published-link"], cwd=repo, check=True)

    private_name = "person" + "@private.test.md"
    (repo / private_name).write_text("clean", encoding="utf-8")
    subprocess.run(["git", "add", private_name], cwd=repo, check=True)

    found = namespace["violations"](repo)
    assert ("direct SSH machine endpoint", Path("metadata.txt")) in found
    assert ("absolute user-home path", Path("published-link")) in found
    assert (
        "tracked path: non-example email address",
        Path(private_name),
    ) in found
