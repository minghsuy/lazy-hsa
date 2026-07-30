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
        "ssh user" + "@my_private_host",
        "scp user" + "@[fd00::1]:/private/file .",
    ):
        assert "direct SSH machine endpoint" in categories(text)
    assert "direct SSH machine endpoint" not in categories("contact user@example.com")
    assert "direct SSH machine endpoint" not in categories("from:auto-confirm@amazon.com")
    assert "direct SSH machine endpoint" not in categories("uses: actions/checkout@v4")
    assert "direct SSH machine endpoint" not in categories("uses: actions/checkout@v4.2.2")
    assert "direct SSH machine endpoint" not in categories("uses: owner/action@main")
    assert "direct SSH machine endpoint" not in categories(
        "uses: owner/action@0123456789abcdef0123456789abcdef01234567"
    )
    assert "direct SSH machine endpoint" not in categories("dependency: npm/pico@2")
    assert "direct SSH machine endpoint" not in categories("npm install package@latest")
    assert "direct SSH machine endpoint" not in categories("npm install --save package@latest")
    assert "direct SSH machine endpoint" not in categories(
        "image: alpine" + "@sha256:" + ("a" * 64)
    )
    assert "direct SSH machine endpoint" in categories("ssh build-action" + "@private-host")
    assert "direct SSH machine endpoint" in categories("ssh build-action" + "@v4.2.2")
    assert "direct SSH machine endpoint" in categories("uses: build-action" + "@private-host")
    assert "direct SSH machine endpoint" in categories("ssh user" + "@v4")
    assert "non-example email address" in categories("contact person" + "@private.test")
    assert "non-example email address" not in categories("contact user@example.com")
    assert "non-example email address" not in categories("from:auto-confirm@amazon.com")

    for home in ("/home/" + "private-user", "/Users/" + "private-user"):
        assert "absolute user-home path" in categories(home)
    for home in (
        "C:" + "/Users/" + "private-user/secret",
        "C:" + "\\Users\\" + "private-user\\secret",
        "c:" + "/users/" + "private-user/secret",
        "c:" + "\\users\\" + "private-user\\secret",
    ):
        assert "absolute user-home path" in categories(home)

    for private_repo in (
        "https://GitHub.com/Minghsuy/" + "private-infra",
        "https://raw.githubusercontent.com/minghsuy/" + "private-infra/main/file",
        "https://api.github.com/repos/minghsuy/" + "private-infra",
    ):
        assert "environment-specific GitHub repository" in categories(private_repo)

    symlink = tmp_path / "published-link"
    symlink.symlink_to("/home/" + "private-user/config")
    read_tracked_text = namespace["read_tracked_text"]
    assert "absolute user-home path" in categories(read_tracked_text(symlink))


def test_public_metadata_guard_scans_paths_bytes_and_git_modes(tmp_path):
    """Tracked names, binary blobs, symlink targets, and gitlinks fail closed."""
    namespace = runpy.run_path(str(REPO_DIR / "scripts" / "check-public-metadata.py"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Metadata Guard Test"], cwd=repo, check=True)

    private_name = "person" + "@private.test.md"
    (repo / private_name).write_text("clean", encoding="utf-8")
    (repo / "binary.dat").write_bytes(b"\xff/home/" + b"private-user/secret")
    (repo / "published-link").symlink_to("/home/" + "private-user/config")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo", f"160000,{commit},vendor"],
        cwd=repo,
        check=True,
    )

    entries = namespace["tracked_entries"](repo)
    assert {mode for mode, _ in entries} >= {"100644", "120000", "160000"}
    found = namespace["violations"](repo)
    assert any(
        category.startswith("tracked path:") and path.name == private_name
        for category, path in found
    )
    assert ("absolute user-home path", Path("binary.dat")) in found
    assert ("absolute user-home path", Path("published-link")) in found
    assert ("unsupported tracked gitlink", Path("vendor")) in found
