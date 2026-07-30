"""Installed-distribution contract tests."""

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
    """Return workflow refs plus refs from every reachable local composite action."""
    refs: list[str] = []
    pending_local_refs: list[str] = []
    for workflow_path in workflow_paths(repo_dir / ".github" / "workflows"):
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
        workflow_refs = executable_uses_refs(workflow)
        refs.extend(workflow_refs)
        pending_local_refs.extend(
            step["uses"]
            for job in workflow.get("jobs", {}).values()
            for step in job.get("steps", [])
            if step.get("uses", "").startswith("./")
        )

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
    jobs = workflow["jobs"]
    security = jobs["security"]
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

    reusable_workflow = workflow_dir / "reusable.yml"
    reusable_workflow.write_text(
        "on: workflow_call\njobs:\n  build:\n    steps: []\n",
        encoding="utf-8",
    )
    (workflow_dir / "build.yaml").write_text(
        "jobs:\n  build:\n    uses: ./.github/workflows/reusable.yml\n",
        encoding="utf-8",
    )
    assert all(uses_ref_is_immutable(ref) for ref in repository_uses_refs(tmp_path))


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
    git_url_key = "u" + "rl"
    git_pushurl_key = "push" + "url"
    git_command = "g" + "it"
    private_scp_remote = "private-host" + ":repo.git"
    windows_repo = "C:" + "\\repos\\private.git"
    escaped_windows_repo = "C:" + "\\\\repos\\\\private.git"
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
        f"{remote_command} prod echo 'Deployment complete.'",
        f"{remote_command} backuphost is",
        # These are syntactically valid remote commands despite reading like
        # prose. The fail-closed guard requires prose to establish context
        # before the transport token, as the negative cases below do.
        f"{remote_command} access is required for deployment.",
        f"{remote_command} config lives in the user profile.",
        f"{remote_command} keys live in the home directory.",
        f"{remote_command} config contains settings for hosts.",
        f"{remote_command} is a remote protocol.",
        f"{transfer_command} access is required for file transfer.",
        f"{remote_command} $'private-host'",
        f"{remote_command} $'private\\x2dhost'",
        f"{copy_command} $'private-host:/private/file' .",
        f"{copy_command} $'private\\055host:/private/file' .",
        remote_command + " owner/user" + "@private-host",
        remote_command + " owner/user" + "@192.168.1.20",
        f"timeout 10 {remote_command} private-host",
        f"time {remote_command} private-host",
        f"time -p {remote_command} private-host",
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
        f"{sync_command} --backup private-host:/path ./destination",
        f"{sync_command} --partial private-host:/path ./destination",
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
        f"{git_url_key} = private-host:repo.git",
        f"{git_pushurl_key}=192.168.1.20:repo.git",
        f"remote.origin.{git_url_key} = [fd00::1]:repo.git",
        f"{git_url_key} = user" + "@private-host:repo.git",
        f'[submodule "private"]\n\t{git_url_key} = private-host:repo.git',
        f"{git_command} clone private-host:repo.git",
        f"/usr/bin/{git_command} ls-remote 192.168.1.20:repo.git",
        f"sudo {git_command} remote add private private-host:repo.git",
        f"{git_command} remote add --m private-host:repo.git public example.com:repo.git",
        f"{git_command} remote add --mi public private-host:repo.git",
        f"{git_command} remote add --tr main public private-host:repo.git",
        f"run: {git_command} clone [fd00::1]:repo.git",
        f"{git_command} clone --branch main private-host:repo.git",
        f"{git_command} fetch --multiple example.com:one.git private-host:two.git",
        f"{git_command} fetch --multi example.com:one.git private-host:two.git",
        f"{git_command} fetch --multip example.com:one.git private-host:two.git",
        f"{git_command} fetch -m example.com:one.git private-host:two.git",
        f"{git_command} fetch -vm example.com:one.git private-host:two.git",
        f"{git_command} fetch -mv example.com:one.git private-host:two.git",
        f"{git_command} fetch -vqm example.com:one.git private-host:two.git",
        f"{git_command} fetch -u private-host:repo.git main",
        f"{git_command} fetch -o trace=1 private-host:repo.git",
        f"{git_command} clone --server-option trace=1 private-host:repo.git",
        f"{git_command} clone --server-op trace=1 private-host:repo.git",
        f"{git_command} clone --ref-format files private-host:repo.git",
        f"{git_command} fetch --server-op trace=1 private-host:repo.git",
        f"{git_command} fetch --negotiation-include tip private-host:repo.git",
        f"{git_command} fetch --negotiation-restrict tip private-host:repo.git",
        f"{git_command} fetch --submodule-prefix path private-host:repo.git",
        f"{git_command} fetch --recurse-submodules-default yes private-host:repo.git",
        f"{git_command} fetch --r private-host:repo.git main",
        f"{git_command} ls-remote --server-op trace=1 private-host:repo.git",
        f"{git_command} pull --server-op trace=1 private-host:repo.git main",
        f"{git_command} pull --c private-host:repo.git main",
        f"{git_command} push --recurse-sub check private-host:repo.git main",
        f"{git_command} push --push-op trace=1 private-host:repo.git main",
        f"{git_command} push --p private-host:repo.git main",
        f"{git_command} fetch --jobs 2 private-host:repo.git",
        f"{git_command} pull --jobs private-host:repo.git main",
        f"{git_command} pull -s recursive private-host:repo.git main",
        f"{git_command} pull -X ours private-host:repo.git main",
        f"{git_command} pull -o trace=1 private-host:repo.git main",
        f"{git_command} pull --cleanup strip private-host:repo.git main",
        f"{git_command} push -u private-host:repo.git main",
        f"{git_command} push -o trace=1 private-host:repo.git main",
        f"{git_command} push --recurse-submodules check private-host:repo.git main",
        f"{git_command} push --repo=private-host:repo.git main",
        f"{git_command} ls-remote -o trace=1 private-host:repo.git",
        f"{git_command} archive --remote=private-host:repo.git main",
        f"{git_command} submodule add private-host:repo.git vendor/private",
        f"{git_command} submodule add --na local-name private-host:repo.git vendor/private",
        f"{git_command} submodule add --refe ./local-ref private-host:repo.git vendor/private",
        f"{git_command} submodule set-url vendor/private private-host:repo.git",
        f"{git_command} config remote.origin.url private-host:repo.git",
        f"{git_command} config --add remote.origin.pushurl private-host:repo.git",
        f"{git_command} config --replace-all remote.origin.url private-host:repo.git '.*'",
        f"{git_command} config -t string remote.origin.url private-host:repo.git",
        f"{git_command} config --typ string remote.origin.url private-host:repo.git",
        f"{git_command} config set --value '.*' remote.origin.url private-host:repo.git",
        f"{git_command} config set --comment message remote.origin.url private-host:repo.git",
        f"{git_command} -c remote.origin.url={private_scp_remote} fetch origin",
        f"{git_command} -c url.private-host:repo.git.insteadOf=mirror clone mirror",
        f"{git_command} -c url.private-host:repo.git.pushInsteadOf=mirror push mirror main",
        f"{git_command} config url.private-host:repo.git.pushInsteadOf mirror",
        f"{git_command} clone -c remote.origin.pushurl={private_scp_remote} example.com:repo.git",
        f"{git_command} clone x:repo.git",
        f"{git_command} clone x:org/repo.git",
        f"{git_command} clone C:repos/private.git",
        f"{git_command} fetch-pack private-host:repo.git main",
        f"{git_command} fetch-pack --exec /usr/bin/git-upload-pack private-host:repo.git main",
        f"{git_command} fetch-pack --shallow-since yesterday private-host:repo.git main",
        f"{git_command} fetch-pack --shallow-exclude main private-host:repo.git main",
        f"{git_command} send-pack private-host:repo.git main",
        f"{git_command} send-pack --p private-host:repo.git main",
        f'Match exec "{remote_command} prod uptime"',
        f'Match exec="{remote_command} private-host"',
        f'Match exec = "{remote_command} private-host"',
        f'Match !exec="{copy_command} private-host:/private/file ."',
        f'Match !exec "{remote_command} private-host"',
        f'Match host *.example.com exec "{shell_command} -c '
        f"'{copy_command} private-host:/private/file .'\"",
        f"Match canonical exec \"env -S '{remote_command} private-host'\"",
        f'Match exec "{relay_command} private-host 22"',
        f'Match exec "! {remote_command} private-host"',
    ):
        assert "direct SSH machine endpoint" in categories(text)
    for prose in (
        f"Use {remote_command} for remote access.",
        f"The {remote_command} client-server protocol supports remote access.",
        f"use {remote_command} private-host for remote access.",
        f"- {remote_command} private-host is the documented syntax.",
        f"retry-wrapper {remote_command} private-host",
        f"The {remote_command} access is required for deployment.",
        f"The {remote_command} config lives in the user profile.",
        f"The {remote_command} keys live in the home directory.",
        f"The {remote_command} config contains settings for hosts.",
        f"Run {remote_command} -V to show the version.",
        f"{remote_command} -V",
        f"{remote_command} $PRIVATE_HOST",
        f"{copy_command} $PRIVATE_SOURCE ./destination",
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
        f"time {remote_command} example.com",
        f"time -p {remote_command} example.com",
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
        f"The {transfer_command} access is required for file transfer.",
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
        f"Use {git_url_key} = private-host:repo.git in config.",
        "path = private-host:repo.git",
        f"{git_url_key} = ./private-host:repo.git",
        f"{git_url_key} = /srv/private-host:repo.git",
        f"{git_url_key} = C:/repos/private.git",
        f"{git_url_key} = {windows_repo}",
        f'{git_url_key} = "{escaped_windows_repo}" # local checkout',
        f"{git_pushurl_key}={windows_repo} # local mirror",
        f"{git_url_key} = example.com:repo.git",
        f"{git_url_key} = user@example.com:repo.git",
        f"{git_url_key} = " + public_clone_user + ":minghsuy/lazy-hsa.git",
        f"{git_url_key} = https://private-host/repo.git",
        "insteadOf = private-host:repo.git",
        f"{git_url_key} = --upload-pack=private-host:repo.git",
        f"{git_url_key} = private-host",
        f"Use {git_command} clone private-host:repo.git in this example.",
        f"echo {git_command} clone private-host:repo.git",
        f"{git_command} clone example.com:repo.git",
        f"{git_command} clone C:/repos/private.git",
        f"{git_command} clone C:\\repos\\private.git",
        f"{git_command} clone 'C:\\repos\\private.git'",
        f"{git_command} clone --template private-host:repo.git example.com:repo.git",
        f"{git_command} clone -u private-host:helper example.com:repo.git",
        f"{git_command} clone --server-option private-host:repo.git example.com:repo.git",
        f"{git_command} ls-remote --upload-pack private-host:repo.git example.com:repo.git",
        f"{git_command} ls-remote -o private-host:repo.git example.com:repo.git",
        f"{git_command} fetch -o private-host:repo.git example.com:repo.git",
        f"{git_command} fetch -u example.com:repo.git private-host:repo.git",
        f"{git_command} fetch -om example.com:repo.git private-host:repo.git",
        f"{git_command} fetch -jm example.com:repo.git private-host:repo.git",
        f"{git_command} fetch -o -m example.com:repo.git private-host:branch",
        f"{git_command} fetch --server-option -m example.com:repo.git private-host:branch",
        f"{git_command} fetch -o --multiple example.com:repo.git private-host:branch",
        f"{git_command} fetch --server-option --multiple example.com:repo.git private-host:branch",
        f"{git_command} fetch --server-op private-host:repo.git example.com:repo.git",
        f"{git_command} remote add --ma private-host:branch public example.com:repo.git",
        f"{git_command} push --push-op private-host:repo.git example.com:repo.git main",
        f"{git_command} pull -s private-host:repo.git example.com:repo.git main",
        f"{git_command} push -o private-host:repo.git example.com:repo.git main",
        f"{git_command} push -u example.com:repo.git main",
        f"{git_command} archive main",
        f"{git_command} show private-host:repo.git",
        f"{git_command} clone " + public_clone_user + ":minghsuy/lazy-hsa.git",
        f'# Match exec "{remote_command} private-host"',
        f'Use Match exec "{remote_command} private-host" in config.',
        f'Match host exec "{remote_command} private-host"',
        f'Match command "{remote_command} private-host"',
        "Match host private-host",
        f'Match exec "{remote_command} example.com"',
        f'Match exec="{remote_command} example.com"',
        f'Match exec = "{remote_command} example.com"',
        f'Match !exec "{remote_command} example.com"',
        "Match exec=",
        "Match exec =",
        "Match exec",
        "Match all",
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
