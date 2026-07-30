#!/usr/bin/env python3
"""Reject environment-specific metadata from the public repository."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

REPO_DIR = Path(__file__).resolve().parents[1]
PUBLIC_REPOSITORY = "minghsuy/lazy-hsa"
ALLOWED_CONTACTS = {
    "auto-confirm@amazon.com",
    "ship-confirm@amazon.com",
}
EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+\x40[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
USER_AT_HOST_PATTERN = re.compile(
    r"(?<![A-Z0-9._%+-])"
    r"[A-Z0-9._%+-]+\x40(?:\[[A-Z0-9:.%_-]+\]|[A-Z0-9._-]+)"
    r"(?![A-Z0-9._-])",
    re.IGNORECASE,
)
SSH_COMMAND = "\x73\x73\x68"
SCP_COMMAND = "\x73\x63\x70"
SFTP_COMMAND = "\x73\x66\x74\x70"
SSH_COMMAND_PREDECESSORS = {
    "$",
    "!",
    "(",
    ";",
    "&&",
    "||",
    "|",
    "if",
    "while",
    "until",
    "then",
    "elif",
    "else",
    "do",
}
SSH_COMMAND_WRAPPERS = {"command", "env", "exec", "sudo"}
SSH_OPTIONS_WITH_ARGUMENT = set("BbcDEeFIiJLlmOoPpQRSWw")
SCP_OPTIONS_WITH_ARGUMENT = set("cDFiJloPSX")
SFTP_OPTIONS_WITH_ARGUMENT = set("BbcDFiJloPRSsX")
ENDPOINT_BEARING_OPTIONS = {"J", "W", "o"}
NETCAT_COMMANDS = {"nc", "ncat", "netcat"}
NETCAT_OPTIONS_WITH_ARGUMENT = set("ceIiMmOPpqsTVwXx")
WRAPPER_SHORT_OPTIONS_WITH_ARGUMENT = {
    "command": set(),
    "env": set("aCSu"),
    "exec": {"a"},
    "sudo": set("CDghpRrTtUu"),
}
WRAPPER_LONG_OPTIONS_WITH_ARGUMENT = {
    "command": set(),
    "env": {"argv0", "chdir", "split-string", "unset"},
    "exec": set(),
    "sudo": {
        "chdir",
        "close-from",
        "group",
        "host",
        "other-user",
        "prompt",
        "role",
        "root",
        "timeout",
        "type",
        "user",
    },
}
HOSTLIKE_SSH_DESTINATION = re.compile(
    r"(?:"
    r"\[[0-9A-F:.%_-]+\]|"
    r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}|"
    r"[0-9A-F]*:[0-9A-F:]+(?:%[A-Z0-9._-]+)?|"
    r"[A-Z0-9][A-Z0-9._-]*[._-][A-Z0-9._-]+"
    r")",
    re.IGNORECASE,
)
SINGLE_LABEL_SSH_DESTINATION = re.compile(r"[A-Z0-9][A-Z0-9-]*", re.IGNORECASE)
SHELL_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
QUALIFIED_PACKAGE_REF = re.compile(
    r"(?<![A-Z0-9_.-])"
    r"[A-Z0-9_.-]+/[A-Z0-9_.-]+\x40[A-Z0-9._/-]+"
    r"(?![A-Z0-9._/-])",
    re.IGNORECASE,
)
CONTEXTUAL_PACKAGE_REFS = (
    re.compile(
        r"\buses:\s*[A-Z0-9_.-]+/[A-Z0-9_.-]+"
        r"\x40[A-Z0-9._/-]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bnpm\s+(?:install|i)(?:\s+--?[A-Z0-9_-]+)*"
        r"\s+(?:"
        r"\x40[A-Z0-9_.-]+/[A-Z0-9_.-]+\x40[A-Z0-9._/-]+|"
        r"[A-Z0-9_.-]+\x40(?:v?[0-9]+(?:\.[0-9]+)*(?:[-+][A-Z0-9.-]+)?|"
        r"latest|next|beta|alpha|canary)"
        r")",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-Z0-9_.:/-]+\x40sha256:[A-F0-9]{32,}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:invoking|direct)\s+[A-Z0-9_.-]+-action"
        r"\x40v[0-9]+(?:\.[0-9]+)*\b",
        re.IGNORECASE,
    ),
)

PATTERNS = {
    "absolute user-home path": re.compile(
        r"(?:(?:/Users|/home)/|[A-Za-z]:[\\/]+Users[\\/]+)"
        r"[A-Za-z0-9._-]+(?=[\\/]|$|[^A-Za-z0-9._-])",
        re.IGNORECASE,
    ),
    "environment-specific GitHub repository": re.compile(
        r"(?:github\.com/|raw\.githubusercontent\.com/|api\.github\.com/repos/)"
        r"minghsuy/"
        r"(?!lazy-hsa(?:\.git)?(?=[^A-Za-z0-9_.-]|$))[A-Za-z0-9_.-]+",
        re.IGNORECASE,
    ),
}


def allowed_reference_spans(text: str) -> tuple[re.Match[str], ...]:
    """Return package, action, and image references that use ``@`` safely."""
    return tuple(QUALIFIED_PACKAGE_REF.finditer(text)) + tuple(
        match for pattern in CONTEXTUAL_PACKAGE_REFS for match in pattern.finditer(text)
    )


def is_within_allowed_reference(
    match: re.Match[str],
    allowed_refs: tuple[re.Match[str], ...],
) -> bool:
    """Return whether a match is wholly contained in a recognized reference."""
    return any(ref.start() <= match.start() and ref.end() >= match.end() for ref in allowed_refs)


def has_disallowed_user_at_host_identifier(
    text: str,
    allowed_refs: tuple[re.Match[str], ...] | None = None,
) -> bool:
    """Reject user-at-host identifiers without attempting to parse shell syntax."""
    allowed_refs = allowed_reference_spans(text) if allowed_refs is None else allowed_refs
    for match in USER_AT_HOST_PATTERN.finditer(text):
        identifier = match.group(0).lower()
        if identifier.endswith("@example.com") or identifier in ALLOWED_CONTACTS:
            continue
        # Package, action, and image references may use branches, semver tags,
        # immutable commit SHAs, or content digests.
        if is_within_allowed_reference(match, allowed_refs):
            continue
        return True
    return False


def shell_tokens(line: str) -> list[str]:
    """Tokenize shell punctuation while retaining a fail-closed fallback."""
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
        lexer.commenters = ""
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return re.findall(r"&&|\|\||[;&|()]|[^\s;&|()]+", line)


def parse_openssh_arguments(
    tokens: list[str],
    command_index: int,
    options_with_argument: set[str],
) -> tuple[list[tuple[str, int]], list[tuple[str, str]]]:
    """Parse operands and short-option arguments for an OpenSSH client."""
    operands: list[tuple[str, int]] = []
    option_arguments: list[tuple[str, str]] = []
    index = command_index + 1
    options_enabled = True
    while index < len(tokens):
        token = tokens[index]
        if token in {";", "&&", "||", "|", "(", ")"}:
            break
        if options_enabled and token == "--":
            options_enabled = False
            index += 1
            continue
        if options_enabled and token.startswith("-") and token != "-":
            option_cluster = token[1:]
            for option_index, option in enumerate(option_cluster):
                if option not in options_with_argument:
                    continue
                attached_argument = option_cluster[option_index + 1 :]
                if attached_argument:
                    option_arguments.append((option, attached_argument))
                elif index + 1 < len(tokens) and tokens[index + 1] not in {
                    ";",
                    "&&",
                    "||",
                    "|",
                    "(",
                    ")",
                }:
                    index += 1
                    option_arguments.append((option, tokens[index]))
                break
            index += 1
            continue
        options_enabled = False
        operands.append((token, index))
        index += 1
    return operands, option_arguments


def consume_wrapper_options(prefix: list[str], index: int, wrapper: str) -> int | None:
    """Consume one wrapper's options and their separate operands."""
    index += 1
    while index < len(prefix):
        token = prefix[index]
        if token == "--":
            return index + 1
        if not token.startswith("-") or token == "-":
            return index
        if token.startswith("--"):
            name, separator, _ = token[2:].partition("=")
            if not separator and name in WRAPPER_LONG_OPTIONS_WITH_ARGUMENT[wrapper]:
                if index + 1 >= len(prefix):
                    return None
                index += 1
            index += 1
            continue
        option_cluster = token[1:]
        for option_index, option in enumerate(option_cluster):
            if option not in WRAPPER_SHORT_OPTIONS_WITH_ARGUMENT[wrapper]:
                continue
            if option_index == len(option_cluster) - 1:
                if index + 1 >= len(prefix):
                    return None
                index += 1
            break
        index += 1
    return index


def ssh_is_in_command_position(tokens: list[str], command_index: int) -> bool:
    """Recognize shell prefixes without mistaking ordinary prose for a command."""
    start = command_index - 1
    while start >= 0 and tokens[start] not in SSH_COMMAND_PREDECESSORS:
        start -= 1
    prefix = tokens[start + 1 : command_index]
    if not prefix:
        return True
    index = 0
    while index < len(prefix) and SHELL_ASSIGNMENT.fullmatch(prefix[index]):
        index += 1
    while index < len(prefix):
        wrapper = prefix[index].rsplit("/", maxsplit=1)[-1]
        if wrapper not in SSH_COMMAND_WRAPPERS:
            return False
        next_index = consume_wrapper_options(prefix, index, wrapper)
        if next_index is None:
            return False
        index = next_index
        while index < len(prefix) and SHELL_ASSIGNMENT.fullmatch(prefix[index]):
            index += 1
    return True


def single_label_destination_is_unambiguous(
    tokens: list[str],
    command_index: int,
    destination_index: int,
    command: str = SSH_COMMAND,
) -> bool:
    """Separate a bare line-start command from a complete prose sentence."""
    trailing = tokens[destination_index + 1 :]
    if not trailing or trailing[0] in {"#", ";", "&&", "||", "|", "(", ")"}:
        return True
    if (
        command_index > 0
        or tokens[command_index] != command
        or destination_index > command_index + 1
    ):
        return True
    return not (len(trailing) >= 2 and trailing[-1].endswith((".", "!", "?")))


def uri_host(destination: str, scheme: str) -> str | None:
    """Return a URI hostname for the expected scheme."""
    try:
        parsed = urlsplit(destination)
        if parsed.scheme.lower() != scheme or not parsed.hostname:
            return None
        return parsed.hostname
    except ValueError:
        return None


def remote_host_is_disallowed(host: str) -> bool:
    """Return whether an explicit remote host is non-example and hostlike."""
    normalized = host.lower().rstrip(".")
    if normalized == "example.com" or normalized.endswith(".example.com"):
        return False
    return bool(
        HOSTLIKE_SSH_DESTINATION.fullmatch(host) or SINGLE_LABEL_SSH_DESTINATION.fullmatch(host)
    )


def endpoint_authority_host(authority: str) -> str | None:
    """Extract a host from ``[user@]host[:port]`` endpoint syntax."""
    authority = authority.strip()
    if not authority or authority.lower() == "none":
        return None
    host_port = authority.rsplit("@", maxsplit=1)[-1]
    if host_port.startswith("["):
        closing_bracket = host_port.find("]")
        return host_port[1:closing_bracket] if closing_bracket > 1 else None
    if host_port.count(":") == 1:
        host, _, _ = host_port.partition(":")
        return host
    return host_port


def openssh_option_value(argument: str) -> tuple[str, str] | None:
    """Split an ``-o`` argument written as ``Key=Value`` or ``Key Value``."""
    key, separator, value = argument.partition("=")
    if separator:
        return key.lower(), value
    parts = argument.split(maxsplit=1)
    return (parts[0].lower(), parts[1]) if len(parts) == 2 else None


def option_endpoint_hosts(
    option: str,
    argument: str,
    inspect_proxy_command: bool = True,
) -> list[str]:
    """Extract endpoint hosts from ``-J``, ``-W``, and selected ``-o`` values."""
    if option == "J":
        return [
            host
            for endpoint in argument.split(",")
            if (host := endpoint_authority_host(endpoint)) is not None
        ]
    if option == "W":
        host = endpoint_authority_host(argument)
        return [host] if host is not None else []
    if option != "o":
        return []
    parsed_option = openssh_option_value(argument)
    if parsed_option is None:
        return []
    normalized_key, value = parsed_option
    if normalized_key == "proxyjump":
        return option_endpoint_hosts("J", value)
    if normalized_key == "hostname":
        host = endpoint_authority_host(value)
        return [host] if host is not None else []
    if normalized_key == "proxycommand" and inspect_proxy_command:
        return proxy_command_hosts(value)
    return []


def proxy_command_hosts(command: str) -> list[str]:
    """Extract ProxyCommand endpoints with a finite, non-recursive worklist."""
    hosts: list[str] = []
    pending = [command]
    inspected: set[str] = set()
    while pending:
        current = pending.pop()
        if current in inspected:
            continue
        inspected.add(current)
        for line in current.replace("\\\n", " ").splitlines():
            tokens = shell_tokens(line)
            for index, token in enumerate(tokens):
                executable = token.rsplit("/", maxsplit=1)[-1]
                if executable == SSH_COMMAND and ssh_is_in_command_position(tokens, index):
                    operands, option_arguments = parse_openssh_arguments(
                        tokens,
                        index,
                        SSH_OPTIONS_WITH_ARGUMENT,
                    )
                    for option, argument in option_arguments:
                        parsed_option = openssh_option_value(argument) if option == "o" else None
                        if parsed_option is not None and parsed_option[0] == "proxycommand":
                            pending.append(parsed_option[1])
                            continue
                        hosts.extend(option_endpoint_hosts(option, argument, False))
                    if operands:
                        destination = operands[0][0]
                        uri_destination = uri_host(destination, "ssh")
                        host = (
                            uri_destination
                            if uri_destination is not None
                            else endpoint_authority_host(destination)
                        )
                        if host is not None:
                            hosts.append(host)
                    continue
                if executable not in NETCAT_COMMANDS or not ssh_is_in_command_position(
                    tokens, index
                ):
                    continue
                operands, option_arguments = parse_openssh_arguments(
                    tokens,
                    index,
                    NETCAT_OPTIONS_WITH_ARGUMENT,
                )
                hosts.extend(
                    host
                    for option, argument in option_arguments
                    if option == "x"
                    for host in option_endpoint_hosts("W", argument, False)
                )
                if operands:
                    host = endpoint_authority_host(operands[0][0])
                    if host is not None:
                        hosts.append(host)
    return hosts


def has_disallowed_option_endpoint(option_arguments: list[tuple[str, str]]) -> bool:
    """Return whether parsed OpenSSH options contain a private endpoint."""
    return any(
        remote_host_is_disallowed(host)
        for option, argument in option_arguments
        if option in ENDPOINT_BEARING_OPTIONS
        for host in option_endpoint_hosts(option, argument)
    )


def scp_remote_host(operand: str) -> str | None:
    """Extract the host from an SCP URI or legacy ``host:path`` operand."""
    uri_destination = uri_host(operand, "scp")
    if uri_destination is not None:
        return uri_destination
    if "://" in operand:
        return None
    if operand.startswith("["):
        closing_bracket = operand.find("]")
        if closing_bracket < 0 or operand[closing_bracket + 1 : closing_bracket + 2] != ":":
            return None
        authority = operand[: closing_bracket + 1]
    else:
        authority, separator, _ = operand.partition(":")
        if not separator:
            return None
    host = authority.rsplit("@", maxsplit=1)[-1]
    return host[1:-1] if host.startswith("[") and host.endswith("]") else host


def sftp_remote_host(operand: str) -> str | None:
    """Extract the host from an SFTP URI or ``[user@]host[:path]`` destination."""
    uri_destination = uri_host(operand, "sftp")
    if uri_destination is not None:
        return uri_destination
    if "://" in operand:
        return None
    if operand.startswith("["):
        closing_bracket = operand.find("]")
        if closing_bracket < 0:
            return None
        authority = operand[: closing_bracket + 1]
    else:
        authority = operand.partition(":")[0]
    host = authority.rsplit("@", maxsplit=1)[-1]
    return host[1:-1] if host.startswith("[") and host.endswith("]") else host


def has_ssh_command_without_user(text: str) -> bool:
    """Reject username-less hostlike SSH destinations in shell command position."""
    normalized = text.replace("\\\n", " ")
    for line in normalized.splitlines():
        tokens = shell_tokens(line)
        for index, token in enumerate(tokens):
            if token.rsplit("/", maxsplit=1)[-1] != SSH_COMMAND:
                continue
            if not ssh_is_in_command_position(tokens, index):
                continue
            operands, option_arguments = parse_openssh_arguments(
                tokens,
                index,
                SSH_OPTIONS_WITH_ARGUMENT,
            )
            if has_disallowed_option_endpoint(option_arguments):
                return True
            if not operands:
                continue
            destination, destination_index = operands[0]
            if "@" in destination:
                continue
            uri_destination = uri_host(destination, "ssh")
            if uri_destination is not None:
                if remote_host_is_disallowed(uri_destination):
                    return True
                continue
            if not remote_host_is_disallowed(destination):
                continue
            if HOSTLIKE_SSH_DESTINATION.fullmatch(destination):
                return True
            if SINGLE_LABEL_SSH_DESTINATION.fullmatch(
                destination
            ) and single_label_destination_is_unambiguous(
                tokens,
                index,
                destination_index,
            ):
                return True
    return False


def has_scp_command_with_remote(text: str) -> bool:
    """Reject non-example remote operands in shell SCP command position."""
    normalized = text.replace("\\\n", " ")
    for line in normalized.splitlines():
        tokens = shell_tokens(line)
        for index, token in enumerate(tokens):
            if token.rsplit("/", maxsplit=1)[-1] != SCP_COMMAND:
                continue
            if not ssh_is_in_command_position(tokens, index):
                continue
            operands, option_arguments = parse_openssh_arguments(
                tokens,
                index,
                SCP_OPTIONS_WITH_ARGUMENT,
            )
            if has_disallowed_option_endpoint(option_arguments):
                return True
            for operand, _ in operands:
                host = scp_remote_host(operand)
                if host is not None and remote_host_is_disallowed(host):
                    return True
    return False


def has_sftp_command_with_remote(text: str) -> bool:
    """Reject non-example endpoints in shell SFTP command position."""
    normalized = text.replace("\\\n", " ")
    for line in normalized.splitlines():
        tokens = shell_tokens(line)
        for index, token in enumerate(tokens):
            if token.rsplit("/", maxsplit=1)[-1] != SFTP_COMMAND:
                continue
            if not ssh_is_in_command_position(tokens, index):
                continue
            operands, option_arguments = parse_openssh_arguments(
                tokens,
                index,
                SFTP_OPTIONS_WITH_ARGUMENT,
            )
            if has_disallowed_option_endpoint(option_arguments):
                return True
            if not operands:
                continue
            destination, destination_index = operands[0]
            host = sftp_remote_host(destination)
            if host is None or not remote_host_is_disallowed(host):
                continue
            if HOSTLIKE_SSH_DESTINATION.fullmatch(host):
                return True
            if SINGLE_LABEL_SSH_DESTINATION.fullmatch(
                host
            ) and single_label_destination_is_unambiguous(
                tokens,
                index,
                destination_index,
                SFTP_COMMAND,
            ):
                return True
    return False


def tracked_entries(repo_dir: Path = REPO_DIR) -> list[tuple[str, Path]]:
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    entries: list[tuple[str, Path]] = []
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, separator, raw_path = entry.partition(b"\t")
        if not separator:
            continue
        mode = metadata.split(maxsplit=1)[0].decode("ascii")
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if not path.startswith(".git/"):
            entries.append((mode, repo_dir / path))
    return entries


def decode_tracked_bytes(data: bytes) -> str:
    """Expose ASCII signatures in binary data and common Unicode encodings."""
    decoded = [data.decode("latin-1")]
    if b"\0" in data:
        decoded.extend(
            data.decode(encoding, errors="replace")
            for encoding in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")
        )
    return "\n".join(decoded)


def read_index_text(repo_dir: Path, relative_path: Path) -> str | None:
    """Read the exact staged blob so filters and missing link targets cannot hide it."""
    result = subprocess.run(
        ["git", "show", f":{relative_path.as_posix()}"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return decode_tracked_bytes(result.stdout)


def metadata_categories(text: str) -> list[str]:
    categories = [category for category, pattern in PATTERNS.items() if pattern.search(text)]
    allowed_refs = allowed_reference_spans(text)
    if (
        has_disallowed_user_at_host_identifier(text, allowed_refs)
        or has_ssh_command_without_user(text)
        or has_scp_command_with_remote(text)
        or has_sftp_command_with_remote(text)
    ):
        categories.append("direct SSH machine endpoint")
    contacts = {
        match.group(0).lower()
        for match in EMAIL_PATTERN.finditer(text)
        if not is_within_allowed_reference(match, allowed_refs)
    }
    if any(
        not contact.endswith("@example.com") and contact not in ALLOWED_CONTACTS
        for contact in contacts
    ):
        categories.append("non-example email address")
    return categories


def violations(repo_dir: Path = REPO_DIR) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for mode, path in tracked_entries(repo_dir):
        relative_path = path.relative_to(repo_dir)
        found.extend(
            (f"tracked path: {category}", relative_path)
            for category in metadata_categories(relative_path.as_posix())
        )
        if mode == "160000":
            found.append(("unsupported tracked gitlink", relative_path))
            continue
        text = read_index_text(repo_dir, relative_path)
        if text is None:
            found.append(("unreadable tracked entry", relative_path))
            continue
        found.extend((category, relative_path) for category in metadata_categories(text))
    return found


def main() -> int:
    found = violations()
    if not found:
        print(f"public metadata guard passed for {PUBLIC_REPOSITORY}")
        return 0
    print("error: environment-specific metadata found in tracked public files")
    for category, path in found:
        print(f"- {path}: {category}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
