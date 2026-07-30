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
    sync_command = "r" + "sync"
    shell_command = "s" + "h"
    ssh_uri = remote_command + "://"
    scp_uri = copy_command + "://"
    sftp_uri = transfer_command + "://"
    rsync_uri = sync_command + "://"
    public_clone_user = "git" + "@github.com"
    local_forward = "Local" + "Forward"
    file_scheme = "file" + ":"
    file_uri = file_scheme + "//"
    unix_home_path = "/" + "home"
    users_path = "/" + "Users"
    windows_users_path = "C:" + users_path
    windows_users_backslash = "C:" + "\\Users"
    checkout_action = "actions/checkout" + "@v4"
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
        f"{remote_command} private-host # uses {checkout_action}",
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
        f"""{remote_command} -o "ProxyCommand={shell_command} -c \
'{remote_command} -W %h:%p private-jump-host'" example.com""",
        f"""{remote_command} -o "ProxyCommand=bash -c \
'{relay_command} private-host 22'" example.com""",
        f"""{remote_command} "-oProxyCommand={shell_command} -c \
'{relay_command} private-host 22'" example.com""",
        f"""{remote_command} -o "ProxyCommand=/bin/{shell_command} -lc \
'{relay_command} private-host 22'" example.com""",
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
        f"{remote_command} -L 8080:private-host:80 example.com",
        f"{remote_command} -L8080:private-host:80 example.com",
        f"{remote_command} -vvL 8080:private-host:80 example.com",
        f"{remote_command} -R '[::1]:8080:[fd00::2]:80' example.com",
        f"{remote_command} -o 'LocalForward 8080 private-host:80' example.com",
        f"{remote_command} -oLocalForward=8080:private-host:80 example.com",
        f"{remote_command} -o 'RemoteForward 8080 private-host:80' example.com",
        f"timeout 10 {remote_command} -L 8080:private-host:80 example.com",
        f"{remote_command} {ssh_uri}private-host",
        f"{remote_command} {ssh_uri}private-host:2222",
        f"{remote_command} {ssh_uri}192.168.1.20",
        f"{remote_command} {ssh_uri}[fd00::1]",
        f"{remote_command} {ssh_uri}[fe80::1%25eth0]",
        f"sudo -u root {remote_command} -F /dev/null {ssh_uri}private-host",
        f"Connect with {ssh_uri}private-host.",
        f"Endpoint: <{ssh_uri}192.168.1.20:2222/path>.",
        f"Documentation ({ssh_uri}[fd00::1]:2222/private/path).",
        f"Endpoint: {ssh_uri.upper()}private-host/private/path",
        f"sudo -u root {remote_command} private-host",
        f"{remote_command} private-host echo {checkout_action}",
        f"{copy_command} private-host:/private/file .",
        f"{copy_command} local-file private-host:/private/file",
        f"{copy_command} -F /dev/null private-host:/private/file .",
        f"sudo -u root {copy_command} -P 2222 local-file private-host:/private/file",
        f"{copy_command} 192.168.1.20:/private/file .",
        f"{copy_command} [fd00::1]:/private/file .",
        f"{copy_command} {scp_uri}private-host/private/file .",
        f"{copy_command} {scp_uri}[fd00::1]/private/file .",
        f"{copy_command} {scp_uri}[fe80::1%25eth0]/private/file .",
        f"{copy_command} user" + "@private-host:/private/file .",
        f"{copy_command} -J private-jump example.com:/private/file .",
        f"timeout 10 {copy_command} private-host:/private/file .",
        f"nohup {copy_command} ./local-file private-host:/private/file",
        f"env -S '{copy_command} private-host:/private/file .'",
        f"env --split-string='{copy_command} private-host:/private/file .'",
        f"sudo {shell_command} -c '{copy_command} private-host:/private/file .'",
        f"{transfer_command} private-host",
        f"{transfer_command} private-host:/private/path",
        f"{transfer_command} user" + "@private-host:/private/path",
        f"{transfer_command} 192.168.1.20",
        f"{transfer_command} [fd00::1]",
        f"{transfer_command} {sftp_uri}private-host/private/path",
        f"{transfer_command} {sftp_uri}192.168.1.20/private/path",
        f"{transfer_command} {sftp_uri}[fd00::1]/private/path",
        f"sudo -u root {transfer_command} -F /dev/null private-host",
        f"{transfer_command} -J private-jump example.com",
        f"{transfer_command} -Jprivate-jump example.com",
        f"{transfer_command} -vvJ private-jump example.com",
        f"{transfer_command} -oProxyJump=private-jump example.com",
        f"{transfer_command} -o HostName=private-host example.com",
        f"timeout 10 {transfer_command} private-host",
        f"nohup {transfer_command} private-host:/private/path",
        f"sudo /bin/bash -lc '{transfer_command} private-host:/private/path'",
        f"{sync_command} private-host:/private/path ./destination",
        f"{sync_command} ./source private-host:/private/path",
        f"{sync_command} private-host::private-module ./destination",
        f"{sync_command} user" + "@private-host:/private/path ./destination",
        f"{sync_command} 192.168.1.20:/private/path ./destination",
        f"{sync_command} [fd00::1]:/private/path ./destination",
        f"{sync_command} {rsync_uri}private-host/private-module ./destination",
        f"{sync_command} {rsync_uri}[fd00::1]/private-module ./destination",
        f"/usr/bin/{sync_command} -av ./source private-host:/private/path",
        f"sudo -u root {sync_command} -e {remote_command} private-host:/private/path ./destination",
        f"env VAR=x {sync_command} --port 873 {rsync_uri}private-host/module ./destination",
        f"{sync_command} -e '{remote_command} -J private-jump' ./source example.com:/destination",
        f"{sync_command} --rsh='{remote_command} -o HostName=private-host' "
        "./source example.com:/destination",
        f"{sync_command} -e '{remote_command} -oProxyJump=private-jump' "
        "./source example.com:/destination",
        f"timeout 10 {sync_command} private-host:/private/path ./destination",
        f"nohup {sync_command} ./source private-host:/private/path",
        f"env -S 'sudo {shell_command} -c "
        f'"{sync_command} private-host:/private/path ./destination"\'',
        f"timeout 10 {shell_command} -c '{copy_command} private-host:/private/file .'",
        f"nohup {shell_command} -c '{transfer_command} private-host:/private/path'",
        f"nice -n 5 {shell_command} -c '{sync_command} private-host:/private/path ./destination'",
        f"busybox {shell_command} -c '{copy_command} private-host:/private/file .'",
        f"{remote_command} -o 'ProxyCommand=timeout 5 {relay_command} private-host 22' example.com",
        f"{remote_command} -o 'ProxyCommand=nohup {relay_command} private-host 22' example.com",
        f"{remote_command} -o 'ProxyCommand=nice -n 5 {relay_command} private-host 22' example.com",
        f"{remote_command} -o 'ProxyCommand=busybox {relay_command} private-host 22' example.com",
        f"Standalone endpoint: {scp_uri}private-host/private/file.",
        f"Standalone endpoint: {sftp_uri}private-host/private/path.",
        f"Standalone endpoint: <{sftp_uri}[fd00::1]:2222/private/path>.",
        f"Standalone endpoint: {rsync_uri}private-host/private-module.",
        f"Standalone endpoint: {rsync_uri.upper()}192.168.1.20/private-module.",
        "HostName private-host",
        "  HostName=192.168.1.20 # deployment endpoint",
        'HostName "[fd00::1]"',
        "ProxyJump private-jump",
        "  ProxyJump=example.com,private-jump",
        f"ProxyCommand {relay_command} private-host 22",
        f"ProxyCommand=timeout 5 {relay_command} private-host 22",
        f"ProxyCommand timeout 5 {shell_command} -c '{relay_command} private-host 22'",
        "LocalForward 8080 private-host:80",
        f"{local_forward}=8080:private-host:80",
        "RemoteForward [::1]:8080 [fd00::2]:80",
        f"run: {remote_command} prod uptime",
        f'run: "{remote_command} private-host"',
        f"command: {copy_command} private-host:/private/file .",
        f"entrypoint: {transfer_command} private-host:/private/path",
        f"script: {sync_command} private-host:/private/path ./destination",
    ):
        assert "direct SSH machine endpoint" in categories(text)
    for prose in (
        f"Use {remote_command} for remote access.",
        f"The {remote_command} client-server protocol supports remote access.",
        f"use {remote_command} private-host for remote access.",
        f"- {remote_command} private-host is the documented syntax.",
        f"retry-wrapper {remote_command} private-host",
        f"{remote_command} access is required for deployment.",
        f"{remote_command} config lives in the user profile.",
        f"{remote_command} keys live in the home directory.",
        f"{remote_command} config contains settings for hosts.",
        f"Run {remote_command} -V to show the version.",
        f"{remote_command} -V",
        f"sudo -u {remote_command} private-host",
        f"sudo --user {remote_command} private-host",
        f"env -u {remote_command} private-host",
        f"exec -a {remote_command} private-host",
        f"{remote_command} example.com",
        f"{remote_command} host.example.com",
        f"{remote_command} {ssh_uri}example.com",
        f"{remote_command} {ssh_uri}host.example.com",
        f"Connect with {ssh_uri}example.com/private/path.",
        f"Connect with {ssh_uri}host.example.com:2222/private/path.",
        f"Connect with {ssh_uri}user@example.com/private/path.",
        f"Malformed {ssh_uri}/private-host has no authority.",
        f"Malformed {ssh_uri}[private-host has an unmatched bracket.",
        f"Do not treat not{ssh_uri}private-host as a URI.",
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
        f"""{remote_command} -o "ProxyCommand={shell_command} -c \
'{remote_command} -W %h:%p example.com'" example.com""",
        f"""{remote_command} -o "ProxyCommand=bash -c \
'{relay_command} example.com 22'" example.com""",
        f"""{remote_command} -o "ProxyCommand={shell_command} -c \
'echo {relay_command} private-host 22'" example.com""",
        f'{remote_command} -o "ProxyCommand={remote_command} -o '
        f"'ProxyCommand={relay_command} example.com 22' example.com\" example.com",
        f'{remote_command} "-oProxyCommand={relay_command} example.com 22" example.com',
        f"{remote_command} -o ProxyCommand=none example.com",
        f"{remote_command} -L private-bind:8080:example.com:80 example.com",
        f"{remote_command} -L 8080:%h:80 example.com",
        f"{remote_command} -L 8080:/tmp/remote.sock example.com",
        f"{remote_command} -R '[fd00::1]:8080:example.com:80' example.com",
        f"{remote_command} -o 'LocalForward 8080 example.com:80' example.com",
        f"{remote_command} -o 'RemoteForward 8080 %h:%p' example.com",
        f"Use {copy_command} private-host:/private/file for copying.",
        f"{copy_command} local-file ./destination",
        f"{copy_command} example.com:/private/file .",
        f"{copy_command} host.example.com:/private/file .",
        f"{copy_command} {scp_uri}example.com/private/file .",
        f"{copy_command} user@example.com:/private/file .",
        f"timeout 10 {copy_command} example.com:/private/file .",
        f"nohup {copy_command} example.com:/private/file .",
        f"Use retry-wrapper {copy_command} private-host:/private/file for copying.",
        f"retry-wrapper {copy_command} private-host:/private/file .",
        f"sudo -u {copy_command} private-host:/private/file .",
        f"env -u {copy_command} private-host:/private/file .",
        f"env -S '{copy_command} example.com:/private/file .'",
        f"sudo {shell_command} -c '{copy_command} example.com:/private/file .'",
        f"Use {transfer_command} private-host for file transfer.",
        f"{transfer_command} access is required for file transfer.",
        f"{transfer_command} example.com",
        f"{transfer_command} host.example.com:/private/path",
        f"{transfer_command} {sftp_uri}example.com/private/path",
        f"{transfer_command} user@example.com:/private/path",
        f"{transfer_command} -J example.com example.com",
        f"{transfer_command} -o HostName=example.com example.com",
        f"timeout 10 {transfer_command} example.com",
        f"nohup {transfer_command} example.com:/private/path",
        f"Use retry-wrapper {transfer_command} private-host:/path for transfer.",
        f"retry-wrapper {transfer_command} private-host:/private/path",
        f"Use {sync_command} private-host:/private/path for synchronization.",
        f"{sync_command} ./source ./destination",
        f"{sync_command} example.com:/private/path ./destination",
        f"{sync_command} host.example.com::module ./destination",
        f"{sync_command} {rsync_uri}example.com/module ./destination",
        f"{sync_command} user@example.com:/private/path ./destination",
        f"{sync_command} {rsync_uri}/local/path ./destination",
        f"{sync_command} --exclude private-host:/pattern ./source ./destination",
        f"{sync_command} ./source --exclude private-host:/pattern ./destination",
        f"{sync_command} -f private-host:/pattern ./source ./destination",
        f"{sync_command} -fprivate-host:/pattern ./source ./destination",
        f"{sync_command} --rsh private-host:/binary ./source ./destination",
        f"{sync_command} --rsync-path private-host:/binary ./source ./destination",
        f"{sync_command} -e '{remote_command} -J example.com' ./source example.com:/destination",
        f"{sync_command} --rsh='{remote_command} -o HostName=example.com' "
        "./source example.com:/destination",
        f"{sync_command} --rsh private-host:/binary ./source ./destination",
        f"timeout 10 {sync_command} example.com:/path ./destination",
        f"nohup {sync_command} ./source example.com:/path",
        f"Use retry-wrapper {sync_command} private-host:/path for synchronization.",
        f"retry-wrapper {sync_command} private-host:/path ./destination",
        f"Standalone endpoint: {scp_uri}example.com/private/file.",
        f"Standalone endpoint: {sftp_uri}example.com/private/path.",
        f"Standalone endpoint: {rsync_uri}host.example.com/private-module.",
        f"Malformed endpoint: {sftp_uri}/private-host.",
        f"Malformed endpoint: {rsync_uri}[private-host.",
        f"Do not treat not{sftp_uri}private-host as a URI.",
        f"Do not treat x-{rsync_uri}private-host as a URI.",
        "HostName example.com",
        "HostName %h",
        "ProxyJump example.com",
        "ProxyJump none",
        f"ProxyCommand {relay_command} example.com 22",
        "LocalForward 8080 example.com:80",
        "LocalForward private-bind:8080:example.com:80",
        "RemoteForward [fd00::1]:8080 example.com:80",
        "# HostName private-host",
        "Describe HostName private-host in prose.",
        "setting: ProxyJump private-jump",
        f"run: {remote_command} example.com",
        f"command: {copy_command} example.com:/private/file .",
        f"entrypoint: {transfer_command} example.com:/private/path",
        f"script: {sync_command} example.com:/path ./destination",
        f"description: {remote_command} private-host",
        f"runbook: {remote_command} private-host",
        f"Example run: {remote_command} private-host",
        f"run: echo {remote_command} private-host",
        f"run: [{remote_command}, private-host]",
        f"run: | {remote_command} private-host",
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
        "npm install " + "@" + "scope/package" + "@private-tag"
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
    for ordinary_contact in (
        "https://intranet.example/users/person" + "@company.com",
        "/srv/users/person" + "@company.com",
        "https://github.example/owner/action" + "@release.dev",
    ):
        assert "non-example email address" in categories(ordinary_contact)
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
    for public_clone in (
        public_clone_user + ":minghsuy/lazy-hsa.git",
        ssh_uri + public_clone_user + "/minghsuy/lazy-hsa.git",
    ):
        assert "direct SSH machine endpoint" not in categories(public_clone)
        assert "non-example email address" not in categories(public_clone)
    private_clone = public_clone_user + ":minghsuy/" + "private-infra.git"
    assert "direct SSH machine endpoint" in categories(private_clone)
    assert "non-example email address" in categories(private_clone)

    for home in (
        "/home/" + "private-user",
        "/Users/" + "private-user",
        "/home/" + "张三/secret",
        "/Users/" + "Åsa/secret",
    ):
        assert "absolute user-home path" in categories(home)
    root_home = "/" + "root"
    for home in (
        root_home,
        root_home + "/",
        root_home + "/.ssh/config",
        "HOME=" + root_home,
    ):
        assert "absolute user-home path" in categories(home)
    for home_uri in (
        file_scheme + unix_home_path + "/private-user/.ssh/config",
        file_uri + unix_home_path + "/private-user/.ssh/config",
        file_uri + "localhost" + unix_home_path + "/private-user/.ssh/config",
        file_uri + users_path + "/Åsa/.ssh/config",
        file_scheme + windows_users_path + "/private-user/.ssh/config",
        file_scheme + "/" + windows_users_path + "/private-user/.ssh/config",
        file_scheme + windows_users_backslash + "\\private-user\\.ssh\\config",
        file_scheme + "/" + windows_users_backslash + "\\private-user\\.ssh\\config",
        file_uri + "/" + windows_users_path + "/private-user/.ssh/config",
        file_uri + unix_home_path + "/%E5%BC%A0%E4%B8%89/.ssh/config",
        file_scheme.upper() + unix_home_path + "/张三/.ssh/config",
        file_uri + root_home + "/.ssh/config",
        "HOME_URI=" + file_scheme + unix_home_path + "/private-user/.ssh/config",
        "(" + file_scheme + unix_home_path + "/private-user/.ssh/config)",
        "'" + file_scheme + unix_home_path + "/private-user/.ssh/config'",
    ):
        assert "absolute user-home path" in categories(home_uri)
    for home in (
        "C:" + "/Users/" + "private-user/secret",
        "C:" + "\\Users\\" + "private-user\\secret",
        "c:" + "/users/" + "private-user/secret",
        "c:" + "\\users\\" + "private-user\\secret",
    ):
        assert "absolute user-home path" in categories(home)
    for non_home in (
        root_home + "ed",
        root_home + "-user",
        root_home + ".txt",
        "/" + "ROOT/private-file",
        "/var" + root_home + "/private-file",
        "." + root_home,
        "https://example.com" + root_home,
        "https://example.com/home/private-user",
        "/api/home/private-user",
        "/v1/Users/private-user",
        "https://example.com/C:/Users/private-user",
        file_uri + "server" + unix_home_path + "/private-user/.ssh/config",
        file_scheme + "home/private-user/.ssh/config",
        file_scheme + "//server" + unix_home_path + "/private-user/.ssh/config",
        file_uri + "/api" + unix_home_path + "/private-user",
        file_uri + unix_home_path,
        file_scheme + "//localhost",
        file_uri + "/rooted/private-file",
        file_uri + "/C:/ProgramData/private-file",
        "not" + file_scheme + unix_home_path + "/private-user",
        "https://example.com/" + file_scheme + unix_home_path + "/private-user/.ssh/config",
        "/prefix/" + file_scheme + unix_home_path + "/private-user/.ssh/config",
        "identifier_" + file_scheme + unix_home_path + "/private-user/.ssh/config",
        "scheme:" + file_scheme + unix_home_path + "/private-user/.ssh/config",
        "path\\" + file_scheme + unix_home_path + "/private-user/.ssh/config",
        "prefix-" + file_scheme + unix_home_path + "/private-user/.ssh/config",
    ):
        assert "absolute user-home path" not in categories(non_home)

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
    utf8_home = "/" + "home" + "/张三/secret"
    decoded = namespace["decode_tracked_bytes"](b"\xff" + utf8_home.encode())
    assert utf8_home in decoded
    assert "absolute user-home path" in namespace["metadata_categories"](decoded)
    (repo / private_name).write_text("clean", encoding="utf-8")
    (repo / "binary.dat").write_bytes(b"\xff/home/" + b"private-user/secret")
    (repo / "utf8-home.dat").write_bytes(b"\xff" + utf8_home.encode())
    (repo / "file-uri.dat").write_text("file:" + utf8_home, encoding="utf-8")
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
    assert ("absolute user-home path", Path("utf8-home.dat")) in found
    assert ("absolute user-home path", Path("file-uri.dat")) in found
    assert ("absolute user-home path", Path("published-link")) in found
    assert ("unsupported tracked gitlink", Path("vendor")) in found
