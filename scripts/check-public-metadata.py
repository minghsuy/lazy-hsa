#!/usr/bin/env python3
"""Reject environment-specific metadata from the public repository."""

from __future__ import annotations

import os
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
        r"\s+(?:\x40[A-Z0-9_.-]+/)?"
        r"[A-Z0-9_.-]+\x40[A-Z0-9._/-]+",
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


def read_tracked_text(path: Path, mode: str = "100644") -> str | None:
    """Read working-tree text while preserving a symlink's published target."""
    try:
        if mode == "120000" or path.is_symlink():
            return os.readlink(path)
        if mode == "160000":
            return None
        data = path.read_bytes()
    except OSError:
        return None
    return decode_tracked_bytes(data)


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
    if has_disallowed_user_at_host_identifier(text):
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
