#!/usr/bin/env python3
"""Reject environment-specific metadata from the public repository."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

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
HOSTLIKE_SSH_DESTINATION = re.compile(
    r"(?:"
    r"\[[0-9A-F:.%_-]+\]|"
    r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}|"
    r"[0-9A-F]*:[0-9A-F:]+|"
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


def ssh_destination(tokens: list[str], command_index: int) -> str | None:
    """Return the destination token after OpenSSH options, if present."""
    index = command_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token in {";", "&&", "||", "|", "(", ")"}:
            return None
        if token == "--":
            index += 1
            return tokens[index] if index < len(tokens) else None
        if not token.startswith("-") or token == "-":
            return token
        option_cluster = token[1:]
        for option_index, option in enumerate(option_cluster):
            if option not in SSH_OPTIONS_WITH_ARGUMENT:
                continue
            if option_index == len(option_cluster) - 1:
                index += 1
            break
        index += 1
    return None


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
    return index == len(prefix) or prefix[index] in SSH_COMMAND_WRAPPERS


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
            destination = ssh_destination(tokens, index)
            if not destination or "@" in destination:
                continue
            normalized_destination = destination.lower().rstrip(".")
            if normalized_destination == "example.com" or normalized_destination.endswith(
                ".example.com"
            ):
                continue
            if HOSTLIKE_SSH_DESTINATION.fullmatch(
                destination
            ) or SINGLE_LABEL_SSH_DESTINATION.fullmatch(destination):
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
    if has_disallowed_user_at_host_identifier(text) or has_ssh_command_without_user(text):
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
