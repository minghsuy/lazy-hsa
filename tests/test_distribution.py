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


def test_public_metadata_guard_handles_ssh_options_and_contacts():
    """User-at-host identifiers and shell SSH destinations cannot bypass the guard."""
    namespace = runpy.run_path(str(REPO_DIR / "scripts" / "check-public-metadata.py"))
    categories = namespace["metadata_categories"]
    private_endpoint = "user" + "@private-host"
    remote_command = "s" + "sh"
    copy_command = "s" + "cp"
    transfer_command = "s" + "ftp"
    relay_command = "n" + "c"
    for text in (
        f"{remote_command} -i identity -p 2222 {private_endpoint}",
        f"{remote_command} -i identity \\\n  {private_endpoint}",
        f"{remote_command} -B eth0 {private_endpoint}",
        f"{remote_command} -o 'ProxyCommand=nc %h %p; true' {private_endpoint}",
        remote_command + " -J jumpuser" + "@private-jump target",
        f"if {remote_command} {private_endpoint}; then true; fi",
        f"result=$({remote_command} {private_endpoint})",
        remote_command + " user" + "@my_private_host",
        "scp user" + "@[fd00::1]:/private/file .",
        f"{remote_command} private-host",
        f"{remote_command} 192.168.1.20",
        f"{remote_command} private-host # contact user@example.com",
        f"{remote_command} private-host echo user@example.com",
        f"{remote_command} private-host # uses actions/checkout@v4",
        f"{remote_command} prod uptime",
        f"{remote_command} backuphost is",
        remote_command + " owner/user" + "@private-host",
        remote_command + " owner/user" + "@192.168.1.20",
        f"timeout 10 {remote_command} private-host",
        f"timeout --signal=TERM 10 {remote_command} private-host",
        f"nohup {remote_command} private-host",
        f"nice -n 5 {remote_command} private-host",
        f"timeout 10 {remote_command} -J private-jump example.com",
        f"/usr/bin/timeout 10 /usr/bin/{remote_command} private-host",
        f"sudo {remote_command} private-host",
        f"command {remote_command} private-host",
        f"env {remote_command} private-host",
        f"exec {remote_command} private-host",
        f"VAR=x {remote_command} private-host",
        f"! {remote_command} private-host",
        f"else {remote_command} private-host",
        f"/usr/bin/{remote_command} private-host",
        f"{remote_command} prod",
        f"sudo {remote_command} prod",
        f"sudo -u root {remote_command} prod",
        f"sudo --user=root {remote_command} prod",
        f"command {remote_command} prod",
        f"command -p {remote_command} prod",
        f"env {remote_command} prod",
        f"env -i VAR=x {remote_command} prod",
        f"env --ignore-environment {remote_command} prod",
        f"exec {remote_command} prod",
        f"exec -a remote-session {remote_command} prod",
        f"VAR=x {remote_command} prod",
        f"! {remote_command} prod",
        f"else {remote_command} prod",
        f"/usr/bin/{remote_command} prod",
        f"true && {remote_command} private-host",
        f"false || {remote_command} private-host",
        f"generate | {remote_command} private-host",
        f"true; {remote_command} private-host",
        f'{remote_command} "private-host"',
        f"{remote_command} -i identity -p 2222 private-host",
        f"{remote_command} -vvF /dev/null private-host",
        f"{remote_command} -vvF/dev/null private-host",
        f"{remote_command} -vv -F /dev/null -p 2222 private-host",
        f"{remote_command} -p2222 private-host",
        f"{remote_command} -o 'ProxyCommand=nc %h %p; true' private-host",
        f"{remote_command} -o 'ProxyCommand={remote_command} -W %h:%p private-jump-host' "
        "example.com",
        f"{remote_command} -o 'ProxyCommand={relay_command} private-host 22' example.com",
        f'{remote_command} "-oProxyCommand={relay_command} private-host 22" example.com',
        f"{remote_command} -o 'ProxyCommand=exec {remote_command} -W %h:%p "
        "private-jump-host' example.com",
        f"{remote_command} -o 'ProxyCommand=env {relay_command} -w 5 private-host 22' example.com",
        f"{remote_command} -o 'ProxyCommand={relay_command} -w5 private-host 22' example.com",
        f"{remote_command} -o 'ProxyCommand={relay_command} -x private-proxy:8080 %h %p' "
        "example.com",
        f'{remote_command} -o "ProxyCommand={remote_command} -o '
        f"'ProxyCommand={relay_command} private-host 22' example.com\" example.com",
        f"{remote_command} -J private-jump example.com",
        f"{remote_command} -Jprivate-jump example.com",
        f"{remote_command} -vvJ private-jump example.com",
        f"{remote_command} -W private-host:443 example.com",
        f"{remote_command} -W private-host:%p example.com",
        f"{remote_command} -Wprivate-host:443 example.com",
        f"{remote_command} -o ProxyJump=private-jump example.com",
        f"{remote_command} -oProxyJump=private-jump example.com",
        f"{remote_command} -o HostName=private-host example.com",
        f"{remote_command} -oHostName=private-host example.com",
        f"{remote_command} ssh://private-host",
        f"{remote_command} ssh://private-host:2222",
        f"{remote_command} ssh://192.168.1.20",
        f"{remote_command} ssh://[fd00::1]",
        f"{remote_command} ssh://[fe80::1%25eth0]",
        f"sudo -u root {remote_command} -F /dev/null ssh://private-host",
        f"sudo -u root {remote_command} private-host",
        f"{remote_command} private-host echo actions/checkout@v4",
        f"{copy_command} private-host:/private/file .",
        f"{copy_command} local-file private-host:/private/file",
        f"{copy_command} -F /dev/null private-host:/private/file .",
        f"sudo -u root {copy_command} -P 2222 local-file private-host:/private/file",
        f"{copy_command} 192.168.1.20:/private/file .",
        f"{copy_command} [fd00::1]:/private/file .",
        f"{copy_command} scp://private-host/private/file .",
        f"{copy_command} scp://[fd00::1]/private/file .",
        f"{copy_command} scp://[fe80::1%25eth0]/private/file .",
        f"{copy_command} user" + "@private-host:/private/file .",
        f"{copy_command} -J private-jump example.com:/private/file .",
        f"{transfer_command} private-host",
        f"{transfer_command} private-host:/private/path",
        f"{transfer_command} user" + "@private-host:/private/path",
        f"{transfer_command} 192.168.1.20",
        f"{transfer_command} [fd00::1]",
        f"{transfer_command} sftp://private-host/private/path",
        f"{transfer_command} sftp://192.168.1.20/private/path",
        f"{transfer_command} sftp://[fd00::1]/private/path",
        f"sudo -u root {transfer_command} -F /dev/null private-host",
        f"{transfer_command} -J private-jump example.com",
        f"{transfer_command} -Jprivate-jump example.com",
        f"{transfer_command} -vvJ private-jump example.com",
        f"{transfer_command} -oProxyJump=private-jump example.com",
        f"{transfer_command} -o HostName=private-host example.com",
    ):
        assert "direct SSH machine endpoint" in categories(text)
    for prose in (
        f"Use {remote_command} for remote access.",
        f"The {remote_command} client-server protocol supports remote access.",
        f"{remote_command} access is required for deployment.",
        f"{remote_command} config lives in the user profile.",
        f"{remote_command} keys live in the home directory.",
        f"{remote_command} config contains settings for hosts.",
        f"Run {remote_command} -V to show the version.",
        f"{remote_command} -V",
        f"Use {remote_command} ssh://private-host for remote access.",
        f"sudo -u {remote_command} private-host",
        f"sudo --user {remote_command} private-host",
        f"env -u {remote_command} private-host",
        f"exec -a {remote_command} private-host",
        f"{remote_command} example.com",
        f"{remote_command} host.example.com",
        f"{remote_command} ssh://example.com",
        f"{remote_command} ssh://host.example.com",
        remote_command + " owner/user" + "@example.com",
        f"timeout 10 {remote_command} example.com",
        f"nohup {remote_command} example.com",
        f"nice -n 5 {remote_command} example.com",
        f"{remote_command} -J example.com example.com",
        f"{remote_command} -W example.com:443 example.com",
        f"{remote_command} -W %h:%p example.com",
        f"{remote_command} -o ProxyJump=example.com example.com",
        f"{remote_command} -o ProxyJump=none example.com",
        f"{remote_command} -o HostName=example.com example.com",
        f"{remote_command} -o 'ProxyCommand={remote_command} -W %h:%p example.com' example.com",
        f"{remote_command} -o 'ProxyCommand={relay_command} %h %p' example.com",
        f"{remote_command} -o 'ProxyCommand={relay_command} -w 5 %h %p' example.com",
        f"{remote_command} -o 'ProxyCommand={relay_command} example.com 22' example.com",
        f"{remote_command} -o 'ProxyCommand={relay_command} -x example.com:8080 %h %p' example.com",
        f'{remote_command} -o "ProxyCommand={remote_command} -o '
        f"'ProxyCommand={relay_command} example.com 22' example.com\" example.com",
        f'{remote_command} "-oProxyCommand={relay_command} example.com 22" example.com',
        f"{remote_command} -o ProxyCommand=none example.com",
        f"Use {copy_command} private-host:/private/file for copying.",
        f"{copy_command} local-file ./destination",
        f"{copy_command} example.com:/private/file .",
        f"{copy_command} host.example.com:/private/file .",
        f"{copy_command} scp://example.com/private/file .",
        f"{copy_command} user@example.com:/private/file .",
        f"Use {transfer_command} private-host for file transfer.",
        f"{transfer_command} access is required for file transfer.",
        f"{transfer_command} example.com",
        f"{transfer_command} host.example.com:/private/path",
        f"{transfer_command} sftp://example.com/private/path",
        f"{transfer_command} user@example.com:/private/path",
        f"{transfer_command} -J example.com example.com",
        f"{transfer_command} -o HostName=example.com example.com",
    ):
        assert "direct SSH machine endpoint" not in categories(prose)
    assert "direct SSH machine endpoint" not in categories("contact user@example.com")
    assert "direct SSH machine endpoint" not in categories("from:auto-confirm@amazon.com")
    assert "direct SSH machine endpoint" not in categories("uses: actions/checkout@v4")
    assert "direct SSH machine endpoint" not in categories("uses: actions/checkout@v4.2.2")
    assert "direct SSH machine endpoint" not in categories("uses: owner/action@main")
    assert "direct SSH machine endpoint" not in categories(
        "uses: owner/action@0123456789abcdef0123456789abcdef01234567"
    )
    assert "direct SSH machine endpoint" not in categories("dependency: npm/pico@2")
    assert "direct SSH machine endpoint" not in categories(
        "dependency: owner/user" + "@private-host"
    )
    assert "direct SSH machine endpoint" not in categories("npm install package@latest")
    assert "direct SSH machine endpoint" not in categories("npm install --save package@latest")
    assert "direct SSH machine endpoint" not in categories("npm install package@2.1.0")
    assert "direct SSH machine endpoint" not in categories(
        "npm install " + "@scope/package@private-tag"
    )
    assert "direct SSH machine endpoint" not in categories(
        "image: alpine" + "@sha256:" + ("a" * 64)
    )
    for reference in (
        "uses: owner/action@release.dev",
        "dependency: npm/pico@release.dev",
    ):
        assert "direct SSH machine endpoint" not in categories(reference)
        assert "non-example email address" not in categories(reference)
    assert "non-example email address" in categories(
        "uses: owner/action@release.dev; contact person" + "@private.test"
    )
    assert "direct SSH machine endpoint" in categories(
        remote_command + " build-action" + "@private-host"
    )
    assert "direct SSH machine endpoint" in categories(remote_command + " build-action" + "@v4.2.2")
    assert "direct SSH machine endpoint" in categories("uses: build-action" + "@private-host")
    assert "direct SSH machine endpoint" in categories(remote_command + " user" + "@v4")
    assert "direct SSH machine endpoint" in categories("npm install user" + "@private-host")
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
