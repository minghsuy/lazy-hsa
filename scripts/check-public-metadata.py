#!/usr/bin/env python3
"""Reject environment-specific metadata from the public repository."""

from __future__ import annotations

import re
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
USER_AT_HOST_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\b",
    re.IGNORECASE,
)
PACKAGE_VERSION_REF = re.compile(r"v?[0-9]+")

PATTERNS = {
    "absolute user-home path": re.compile(r"(?:/Users|/home)/[A-Za-z0-9._-]+/"),
    "environment-specific GitHub repository": re.compile(
        r"github\.com/minghsuy/"
        r"(?!lazy-hsa(?:\.git)?(?=$|[^A-Za-z0-9_.-]))[A-Za-z0-9_.-]+",
    ),
}


def has_disallowed_user_at_host_identifier(text: str) -> bool:
    """Reject user-at-host identifiers without attempting to parse shell syntax."""
    for match in USER_AT_HOST_PATTERN.finditer(text):
        identifier = match.group(0).lower()
        local, host = identifier.rsplit("@", maxsplit=1)
        if identifier.endswith("@example.com") or identifier in ALLOWED_CONTACTS:
            continue
        # Slash-qualified package version refs and action-name version refs are
        # not user-at-host identifiers.
        if PACKAGE_VERSION_REF.fullmatch(host) and (
            (match.start() > 0 and text[match.start() - 1] == "/") or local.endswith("-action")
        ):
            continue
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
    categories = [category for category, pattern in PATTERNS.items() if pattern.search(text)]
    if has_disallowed_user_at_host_identifier(text):
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
