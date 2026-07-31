#!/usr/bin/env python3
"""Reject high-signal environment metadata from the public Git index.

This guard is deliberately context-free. It detects the metadata forms that
were removed for issue #6; it is not a shell, SSH, Git, or environment parser.
Transport-aware inspection belongs in a separately designed scanner.
"""

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
    r"\b[A-Z0-9._%+-]+\x40[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
USER_AT_HOST_PATTERN = re.compile(
    r"(?<![A-Z0-9._%+-])"
    r"[A-Z0-9._%+-]+\x40(?:\[[A-Z0-9:.%_-]+\]|[A-Z0-9._-]+)"
    r"(?![A-Z0-9._-])",
    re.IGNORECASE,
)
REFERENCE_PATTERNS = (
    re.compile(
        r"\buses:\s*(?:[A-Z0-9_.-]+/)+[A-Z0-9_.-]+\x40[A-Z0-9._/-]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<![A-Z0-9._/-])[A-Z0-9_.-]+/[A-Z0-9_.-]+\x40"
        r"(?:v?[0-9]+(?:\.[0-9]+)*(?:[-+][A-Z0-9.-]+)?|[A-F0-9]{40})"
        r"(?:/[A-Z0-9._/-]+)?(?![A-Z0-9._/-])",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<![A-Z0-9._/-])[A-Z0-9_.-]+-action\x40"
        r"(?:v?[0-9]+(?:\.[0-9]+)*(?:[-+][A-Z0-9.-]+)?|[A-F0-9]{40})"
        r"(?![A-Z0-9._/-])",
        re.IGNORECASE,
    ),
    re.compile(
        r"https://cdn\.jsdelivr\.net/npm/"
        r"(?:\x40[A-Z0-9_.-]+/)?[A-Z0-9_.-]+\x40[A-Z0-9._/-]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:ssh://)?git\x40github\.com[:/]minghsuy/lazy-hsa(?:\.git)?"
        r"(?![A-Z0-9._/-])",
        re.IGNORECASE,
    ),
)
ABSOLUTE_USER_HOME_PATTERN = re.compile(
    r"(?:(?<![\w.:/-])(?:/Users|/home)/[\w.-]+"
    r"(?=[\\/]|$|[^\w.-])|"
    r"(?<![\w./\\-])[A-Z]:[\\/]+Users[\\/]+[\w.-]+"
    r"(?=[\\/]|$|[^\w.-])|"
    r"(?<![A-Z0-9._/-])(?-i:/root)(?=/|$))",
    re.IGNORECASE,
)
PRIVATE_GITHUB_REPOSITORY_PATTERN = re.compile(
    r"(?:github\.com/|raw\.githubusercontent\.com/|api\.github\.com/repos/)"
    r"minghsuy/"
    r"(?!lazy-hsa(?:\.git)?(?=[^A-Z0-9_.-]|$))[A-Z0-9_.-]+",
    re.IGNORECASE,
)


def allowed_reference_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Return spans where ``@`` is part of a package, action, or public clone."""
    return tuple(match.span() for pattern in REFERENCE_PATTERNS for match in pattern.finditer(text))


def is_allowed_reference(
    match: re.Match[str],
    spans: tuple[tuple[int, int], ...],
) -> bool:
    """Return whether a match is contained in a recognized public reference."""
    return any(start <= match.start() and end >= match.end() for start, end in spans)


def metadata_categories(text: str) -> list[str]:
    """Return the high-signal public metadata categories present in text."""
    categories: list[str] = []
    if ABSOLUTE_USER_HOME_PATTERN.search(text):
        categories.append("absolute user-home path")
    if PRIVATE_GITHUB_REPOSITORY_PATTERN.search(text):
        categories.append("environment-specific GitHub repository")

    reference_spans = allowed_reference_spans(text)
    identifiers = [
        match
        for match in USER_AT_HOST_PATTERN.finditer(text)
        if not is_allowed_reference(match, reference_spans)
    ]
    if any(
        not match.group(0).lower().endswith("@example.com")
        and match.group(0).lower() not in ALLOWED_CONTACTS
        for match in identifiers
    ):
        categories.append("direct SSH machine endpoint")

    contacts = [
        match
        for match in EMAIL_PATTERN.finditer(text)
        if not is_allowed_reference(match, reference_spans)
    ]
    if any(
        not match.group(0).lower().endswith("@example.com")
        and match.group(0).lower() not in ALLOWED_CONTACTS
        for match in contacts
    ):
        categories.append("non-example email address")
    return categories


def tracked_paths(repo_dir: Path) -> list[Path]:
    """Return paths represented by the exact staged Git index."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    return [
        Path(raw.decode("utf-8", errors="surrogateescape"))
        for raw in result.stdout.split(b"\0")
        if raw
    ]


def read_index_text(repo_dir: Path, relative_path: Path) -> str | None:
    """Read an exact index blob, including a tracked symlink's target."""
    result = subprocess.run(
        ["git", "show", f":{relative_path.as_posix()}"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="ignore")


def violations(repo_dir: Path = REPO_DIR) -> list[tuple[str, Path]]:
    """Return metadata violations in tracked names and exact index blobs."""
    found: list[tuple[str, Path]] = []
    for relative_path in tracked_paths(repo_dir):
        found.extend(
            (f"tracked path: {category}", relative_path)
            for category in metadata_categories(relative_path.as_posix())
        )
        text = read_index_text(repo_dir, relative_path)
        if text is None:
            found.append(("unreadable tracked entry", relative_path))
            continue
        found.extend((category, relative_path) for category in metadata_categories(text))
    return found


def main() -> int:
    """Run the public-tree guard."""
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
