"""Installed-distribution contract tests."""

import runpy
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]


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


def test_public_tree_has_no_environment_metadata():
    """Public package history must not regain local infrastructure details."""
    result = subprocess.run(
        [REPO_DIR / "scripts" / "check-public-metadata.py"],
        cwd=REPO_DIR,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_public_metadata_guard_handles_ssh_options_and_contacts(tmp_path):
    """Every disallowed user-at-host token is caught without shell parsing."""
    namespace = runpy.run_path(str(REPO_DIR / "scripts" / "check-public-metadata.py"))
    categories = namespace["metadata_categories"]
    private_endpoint = "user" + "@private-host"
    for text in (
        f"ssh -i identity -p 2222 {private_endpoint}",
        f"ssh -i identity \\\n  {private_endpoint}",
        f"ssh -B eth0 {private_endpoint}",
        f"ssh -o 'ProxyCommand=nc %h %p; true' {private_endpoint}",
        "ssh -J jumpuser" + "@private-jump target",
        f"if ssh {private_endpoint}; then true; fi",
        f"result=$(ssh {private_endpoint})",
    ):
        assert "direct SSH machine endpoint" in categories(text)
    assert "direct SSH machine endpoint" not in categories("contact user@example.com")
    assert "direct SSH machine endpoint" not in categories("from:auto-confirm@amazon.com")
    assert "direct SSH machine endpoint" not in categories("uses: actions/checkout@v4")
    assert "direct SSH machine endpoint" not in categories("dependency: npm/pico@2")
    assert "direct SSH machine endpoint" not in categories("claude-code-action@v1")
    assert "direct SSH machine endpoint" in categories("ssh user" + "@v4")
    assert "non-example email address" in categories("contact person" + "@private.test")
    assert "non-example email address" not in categories("contact user@example.com")
    assert "non-example email address" not in categories("from:auto-confirm@amazon.com")

    for home in ("/home/" + "private-user", "/Users/" + "private-user"):
        assert "absolute user-home path" in categories(home)

    symlink = tmp_path / "published-link"
    symlink.symlink_to("/home/" + "private-user/config")
    read_tracked_text = namespace["read_tracked_text"]
    assert "absolute user-home path" in categories(read_tracked_text(symlink))
