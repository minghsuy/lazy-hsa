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
SINGLE_LABEL_PROSE_CONTINUATIONS = {"are", "is", "lives", "was", "were"}
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


def has_disallowed_user_at_host_identifier(text: str) -> bool:
    """Reject user-at-host identifiers without attempting to parse shell syntax."""
    allowed_refs = tuple(QUALIFIED_PACKAGE_REF.finditer(text)) + tuple(
        match for pattern in CONTEXTUAL_PACKAGE_REFS for match in pattern.finditer(text)
    )
    for match in USER_AT_HOST_PATTERN.finditer(text):
        identifier = match.group(0).lower()
        if identifier.endswith("@example.com") or identifier in ALLOWED_CONTACTS:
            continue
        # Package, action, and image references may use branches, semver tags,
        # immutable commit SHAs, or content digests.
        if any(ref.start() <= match.start() and ref.end() >= match.end() for ref in allowed_refs):
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


def ssh_destination(tokens: list[str], command_index: int) -> tuple[str, int] | None:
    """Return the destination token and its index after OpenSSH options."""
    index = command_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token in {";", "&&", "||", "|", "(", ")"}:
            return None
        if token == "--":
            index += 1
            return (tokens[index], index) if index < len(tokens) else None
        if not token.startswith("-") or token == "-":
            return token, index
        option_cluster = token[1:]
        for option_index, option in enumerate(option_cluster):
            if option not in SSH_OPTIONS_WITH_ARGUMENT:
                continue
            if option_index == len(option_cluster) - 1:
                index += 1
            break
        index += 1
    return None


def command_operands(
    tokens: list[str],
    command_index: int,
    options_with_argument: set[str],
) -> list[str]:
    """Return command operands after consuming short options and their arguments."""
    operands: list[str] = []
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
                if option_index == len(option_cluster) - 1:
                    index += 1
                break
            index += 1
            continue
        options_enabled = False
        operands.append(token)
        index += 1
    return operands


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
) -> bool:
    """Avoid treating a sentence beginning with ``ssh <noun>`` as a command."""
    trailing = tokens[destination_index + 1 :]
    if not trailing or trailing[0] in {"#", ";", "&&", "||", "|", "(", ")"}:
        return True
    if (
        command_index > 0
        or tokens[command_index] != SSH_COMMAND
        or destination_index > command_index + 1
    ):
        return True
    return trailing[0].lower() not in SINGLE_LABEL_PROSE_CONTINUATIONS


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
            destination_result = ssh_destination(tokens, index)
            if destination_result is None:
                continue
            destination, destination_index = destination_result
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
            for operand in command_operands(tokens, index, SCP_OPTIONS_WITH_ARGUMENT):
                host = scp_remote_host(operand)
                if host is not None and remote_host_is_disallowed(host):
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
    if (
        has_disallowed_user_at_host_identifier(text)
        or has_ssh_command_without_user(text)
        or has_scp_command_with_remote(text)
    ):
        categories.append("direct SSH machine endpoint")
    contacts = {match.group(0).lower() for match in EMAIL_PATTERN.finditer(text)}
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
