#!/usr/bin/env python3
"""Reject environment-specific metadata from the public repository."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
PUBLIC_REPOSITORY = "minghsuy/lazy-hsa"

PATTERNS = {
    "absolute user-home path": re.compile(r"(?:/Users|/home)/[A-Za-z0-9._-]+/"),
    "direct SSH machine endpoint": re.compile(r"\bssh\s+\S+@\S+"),
    "non-example email address": re.compile(
        r"\b[A-Z0-9._%+-]+@(?!example\.com\b)[A-Z0-9.-]+\.[A-Z]{2,}\b",
        re.IGNORECASE,
    ),
    "environment-specific GitHub repository": re.compile(
        r"github\.com/minghsuy/"
        r"(?!lazy-hsa(?:\.git)?(?=$|[^A-Za-z0-9_.-]))[A-Za-z0-9_.-]+",
    ),
}


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


def violations() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for path in tracked_files():
        relative_path = path.relative_to(REPO_DIR)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for category, pattern in PATTERNS.items():
            if category == "non-example email address" and not (
                relative_path.name == "README.md"
                or relative_path.parts[0] in {".github", "docs", "scripts"}
            ):
                continue
            if pattern.search(text):
                found.append((category, relative_path))
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
