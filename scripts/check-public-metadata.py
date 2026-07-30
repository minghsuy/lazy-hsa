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
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)

PATTERNS = {
    "absolute user-home path": re.compile(r"(?:/Users|/home)/[A-Za-z0-9._-]+/"),
    "environment-specific GitHub repository": re.compile(
        r"github\.com/minghsuy/"
        r"(?!lazy-hsa(?:\.git)?(?=$|[^A-Za-z0-9_.-]))[A-Za-z0-9_.-]+",
    ),
}
SSH_DESTINATION = re.compile(r"[A-Za-z0-9._-]+@[A-Za-z0-9._-]+")
SSH_COMMAND = re.compile(r"(?m)(?:^[ \t]*|[;&|][ \t]*|\$[ \t]+)ssh(?=[ \t])")
SSH_OPTIONS_WITH_ARGUMENT = set("bcDEeFIiJLlmOo pQRSWw".replace(" ", ""))


def has_direct_ssh_endpoint(text: str) -> bool:
    """Return whether text contains a shell SSH command with a user@host target."""
    normalized = re.sub(r"\\\r?\n[ \t]*", " ", text)
    for match in SSH_COMMAND.finditer(normalized):
        ssh_start = match.end() - len("ssh")
        command = re.split(r"[;&|\n]", normalized[ssh_start:], maxsplit=1)[0]
        try:
            tokens = shlex.split(command)
        except ValueError:
            continue
        if not tokens or tokens[0] != "ssh":
            continue
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token == "--":
                index += 1
                break
            if not token.startswith("-") or token == "-":
                break
            option = token[1:2]
            if option in SSH_OPTIONS_WITH_ARGUMENT and len(token) == 2:
                index += 2
            else:
                index += 1
        if index < len(tokens) and SSH_DESTINATION.fullmatch(tokens[index]):
            return True
    return False


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_DIR,
        check=True,
        capture_output=True,
    )
    return [
        REPO_DIR / entry.decode()
        for entry in result.stdout.split(b"\0")
        if entry and not entry.startswith(b".git/")
    ]


def metadata_categories(text: str) -> list[str]:
    categories = [
        category for category, pattern in PATTERNS.items() if pattern.search(text)
    ]
    if has_direct_ssh_endpoint(text):
        categories.append("direct SSH machine endpoint")
    contacts = {match.group(0).lower() for match in EMAIL_PATTERN.finditer(text)}
    if any(
        not contact.endswith("@example.com") and contact not in ALLOWED_CONTACTS
        for contact in contacts
    ):
        categories.append("non-example email address")
    return categories


def violations() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for path in tracked_files():
        relative_path = path.relative_to(REPO_DIR)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found.extend(
            (category, relative_path) for category in metadata_categories(text)
        )
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
