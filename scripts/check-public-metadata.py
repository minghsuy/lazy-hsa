#!/usr/bin/env python3
"""Reject environment-specific metadata from the public repository."""

from __future__ import annotations

import codecs
import re
import shlex
import subprocess
from contextlib import suppress
from pathlib import Path
from urllib.parse import unquote, urlsplit

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
RSYNC_COMMAND = "\x72\x73\x79\x6e\x63"
GIT_COMMAND = "\x67\x69\x74"
FILE_URI_SCHEME = "\x66\x69\x6c\x65"
STANDALONE_REMOTE_URI_SCHEMES = {
    SSH_COMMAND,
    SCP_COMMAND,
    SFTP_COMMAND,
    RSYNC_COMMAND,
}
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
PROCESS_COMMAND_WRAPPERS = {"busybox", "nice", "nohup", "time", "timeout"}
SSH_OPTIONS_WITH_ARGUMENT = set("BbcDEeFIiJLlmOoPpQRSWw")
SCP_OPTIONS_WITH_ARGUMENT = set("cDFiJloPSX")
SFTP_OPTIONS_WITH_ARGUMENT = set("BbcDFiJloPRSsX")
RSYNC_OPTIONS_WITH_ARGUMENT = set("BefMT@")
RSYNC_LONG_OPTIONS_WITH_ARGUMENT = {
    "address",
    "backup-dir",
    "block-size",
    "bwlimit",
    "cc",
    "checksum-seed",
    "checksum-choice",
    "chmod",
    "chown",
    "compare-dest",
    "compress-choice",
    "compress-level",
    "contimeout",
    "copy-as",
    "copy-dest",
    "debug",
    "early-input",
    "exclude",
    "exclude-from",
    "files-from",
    "filter",
    "groupmap",
    "iconv",
    "include",
    "include-from",
    "info",
    "link-dest",
    "log-file",
    "log-file-format",
    "max-alloc",
    "max-delete",
    "max-size",
    "min-size",
    "modify-window",
    "only-write-batch",
    "outbuf",
    "out-format",
    "partial-dir",
    "password-file",
    "port",
    "protocol",
    "read-batch",
    "remote-option",
    "rsh",
    "rsync-path",
    "skip-compress",
    "sockopts",
    "stderr",
    "stop-after",
    "stop-at",
    "suffix",
    "temp-dir",
    "timeout",
    "usermap",
    "write-batch",
    "zc",
    "zl",
}
GIT_GLOBAL_OPTIONS_WITH_ARGUMENT = {"C", "c"}
GIT_GLOBAL_LONG_OPTIONS_WITH_ARGUMENT = {
    "config-env",
    "git-dir",
    "namespace",
    "super-prefix",
    "work-tree",
}
GIT_REMOTE_OPTIONS_WITH_ARGUMENT = {
    "archive": {"o"},
    "clone": set("bcjou"),
    "fetch": set("jo"),
    "fetch-pack": set(),
    "ls-remote": {"o"},
    "pull": set("Xos"),
    "push": {"o"},
    "send-pack": set(),
}
GIT_REMOTE_LONG_OPTIONS_WITH_ARGUMENT = {
    "archive": {
        "add-file",
        "add-virtual-file",
        "exec",
        "format",
        "mtime",
        "output",
        "prefix",
        "remote",
    },
    "clone": {
        "branch",
        "bundle-uri",
        "config",
        "depth",
        "filter",
        "jobs",
        "origin",
        "reference",
        "reference-if-able",
        "ref-format",
        "revision",
        "server-option",
        "separate-git-dir",
        "shallow-exclude",
        "shallow-since",
        "template",
        "upload-pack",
    },
    "fetch": {
        "depth",
        "deepen",
        "filter",
        "jobs",
        "negotiation-include",
        "negotiation-restrict",
        "negotiation-tip",
        "recurse-submodules-default",
        "server-option",
        "refmap",
        "shallow-exclude",
        "shallow-since",
        "submodule-prefix",
        "upload-pack",
    },
    "fetch-pack": {
        "deepen-not",
        "deepen-since",
        "depth",
        "exec",
        "server-option",
        "shallow-exclude",
        "shallow-since",
        "upload-pack",
    },
    "ls-remote": {"server-option", "sort", "upload-pack"},
    "pull": {
        "cleanup",
        "depth",
        "deepen",
        "filter",
        "negotiation-tip",
        "server-option",
        "shallow-exclude",
        "shallow-since",
        "strategy",
        "strategy-option",
        "upload-pack",
    },
    "push": {
        "exec",
        "push-option",
        "receive-pack",
        "recurse-submodules",
        "repo",
    },
    "send-pack": {"exec", "push-option", "receive-pack", "remote"},
}
GIT_REMOTE_LONG_FLAGS = {
    "archive": {"list", "verbose", "worktree-attributes"},
    "clone": {
        "also-filter-submodules",
        "bare",
        "checkout",
        "dissociate",
        "hardlinks",
        "ipv4",
        "ipv6",
        "local",
        "mirror",
        "no-checkout",
        "no-hardlinks",
        "no-tags",
        "progress",
        "quiet",
        "recursive",
        "recurse-submodules",
        "reject-shallow",
        "remote-submodules",
        "shared",
        "shallow-submodules",
        "single-branch",
        "sparse",
        "tags",
        "verbose",
    },
    "fetch": {
        "all",
        "append",
        "atomic",
        "auto-gc",
        "auto-maintenance",
        "dry-run",
        "force",
        "ipv4",
        "ipv6",
        "keep",
        "multiple",
        "negotiate-only",
        "porcelain",
        "prefetch",
        "progress",
        "prune",
        "prune-tags",
        "quiet",
        "recurse-submodules",
        "refetch",
        "set-upstream",
        "show-forced-updates",
        "stdin",
        "tags",
        "unshallow",
        "update-head-ok",
        "update-shallow",
        "verbose",
        "write-commit-graph",
        "write-fetch-head",
    },
    "fetch-pack": {
        "all",
        "diag-url",
        "include-tag",
        "keep",
        "no-progress",
        "quiet",
        "stdin",
        "thin",
        "verbose",
    },
    "ls-remote": {
        "exit-code",
        "get-url",
        "heads",
        "quiet",
        "refs",
        "symref",
        "tags",
    },
    "pull": {
        "all",
        "allow-unrelated-histories",
        "append",
        "autostash",
        "commit",
        "dry-run",
        "edit",
        "ff",
        "ff-only",
        "force",
        "gpg-sign",
        "ipv4",
        "ipv6",
        "jobs",
        "keep",
        "log",
        "progress",
        "prune",
        "quiet",
        "rebase",
        "recurse-submodules",
        "set-upstream",
        "show-forced-updates",
        "signoff",
        "squash",
        "stat",
        "tags",
        "unshallow",
        "update-shallow",
        "verbose",
        "verify",
        "verify-signatures",
    },
    "push": {
        "all",
        "atomic",
        "branches",
        "delete",
        "dry-run",
        "follow-tags",
        "force",
        "force-if-includes",
        "force-with-lease",
        "ipv4",
        "ipv6",
        "mirror",
        "porcelain",
        "progress",
        "prune",
        "set-upstream",
        "signed",
        "tags",
        "thin",
        "verbose",
        "verify",
    },
    "send-pack": {
        "all",
        "atomic",
        "dry-run",
        "force",
        "force-if-includes",
        "force-with-lease",
        "helper-status",
        "mirror",
        "progress",
        "signed",
        "stateless-rpc",
        "stdin",
        "thin",
        "verbose",
    },
}
for _subcommand, _flags in GIT_REMOTE_LONG_FLAGS.items():
    _flags.update(
        f"no-{option}"
        for option in _flags | GIT_REMOTE_LONG_OPTIONS_WITH_ARGUMENT[_subcommand]
        if not option.startswith("no-")
    )
GIT_REMOTE_SUBCOMMANDS = set(GIT_REMOTE_OPTIONS_WITH_ARGUMENT)
GIT_REMOTE_MANAGEMENT_OPTIONS_WITH_ARGUMENT = set("mt")
GIT_REMOTE_MANAGEMENT_LONG_OPTIONS_WITH_ARGUMENT = {"master", "track"}
GIT_REMOTE_MANAGEMENT_LONG_FLAGS = {
    "add",
    "delete",
    "fetch",
    "mirror",
    "no-fetch",
    "no-mirror",
    "no-tags",
    "push",
    "tags",
}
GIT_SUBMODULE_OPTIONS_WITH_ARGUMENT = {"b"}
GIT_SUBMODULE_LONG_OPTIONS_WITH_ARGUMENT = {
    "branch",
    "depth",
    "filter",
    "name",
    "reference",
    "ref-format",
}
GIT_SUBMODULE_LONG_FLAGS = {
    "all",
    "cached",
    "checkout",
    "default",
    "files",
    "force",
    "init",
    "merge",
    "no-fetch",
    "no-recommend-shallow",
    "no-single-branch",
    "quiet",
    "rebase",
    "recommend-shallow",
    "recursive",
    "remote",
    "single-branch",
}
GIT_CONFIG_OPTIONS_WITH_ARGUMENT = {"f", "t"}
GIT_CONFIG_LONG_OPTIONS_WITH_ARGUMENT = {
    "blob",
    "comment",
    "default",
    "file",
    "type",
    "value",
}
GIT_CONFIG_LONG_FLAGS = {
    "add",
    "all",
    "append",
    "bool",
    "bool-or-int",
    "bool-or-str",
    "edit",
    "expiry-date",
    "fixed-value",
    "get",
    "get-all",
    "get-color",
    "get-colorbool",
    "get-regexp",
    "get-urlmatch",
    "global",
    "includes",
    "int",
    "list",
    "local",
    "name-only",
    "null",
    "path",
    "remove-section",
    "rename-section",
    "replace-all",
    "show-origin",
    "show-scope",
    "system",
    "unset",
    "unset-all",
    "worktree",
}
GIT_CONFIG_LONG_FLAGS.update(
    f"no-{option}"
    for option in GIT_CONFIG_LONG_FLAGS | GIT_CONFIG_LONG_OPTIONS_WITH_ARGUMENT
    if not option.startswith("no-")
)
ENDPOINT_BEARING_OPTIONS = {"J", "L", "R", "W", "o"}
NETCAT_COMMANDS = {"nc", "ncat", "netcat"}
NETCAT_OPTIONS_WITH_ARGUMENT = set("ceIiMmOPpqsTVwXx")
SHELL_COMMANDS = {"bash", "dash", "ksh", "sh", "zsh"}
SHELL_OPTIONS_WITH_ARGUMENT = {"c", "O", "o"}
SHELL_LONG_OPTIONS_WITH_ARGUMENT = {"init-file", "rcfile"}
INLINE_YAML_COMMAND = re.compile(r"^\s*(?:-\s*)?(?:run|command|entrypoint|script)\s*:\s*(.*?)\s*$")
ANSI_C_QUOTED = re.compile(r"\$'((?:\\.|[^'\\])*)'")
BARE_WINDOWS_SHELL_PATH = re.compile(r"(?<!\S)([A-Za-z]:\\[^\s;&|()]+)")
CONFIG_ASSIGNMENT = re.compile(r"^\s*([^#\s=]+)\s*=\s*(.*)$")
RAW_GIT_URL_ASSIGNMENT = re.compile(
    r"^\s*(?:[A-Z0-9_.-]+\.)?(?:url|pushurl)\s*=\s*(.*)$",
    re.IGNORECASE,
)
OPENSSH_MATCH_FLAGS = {"all", "canonical", "final"}
OPENSSH_MATCH_VALUE_CRITERIA = {
    "command",
    "exec",
    "host",
    "localnetwork",
    "localuser",
    "originalhost",
    "tagged",
    "user",
}
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
ENV_LONG_OPTIONS = WRAPPER_LONG_OPTIONS_WITH_ARGUMENT["env"] | {
    "block-signal",
    "debug",
    "default-signal",
    "help",
    "ignore-environment",
    "ignore-signal",
    "list-signal-handling",
    "null",
    "version",
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
SHELL_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=.*")
SIMPLE_SHELL_REDIRECTION = re.compile(r"(?<!\S)(?:\d+)?(?:>>?|<<?)[A-Za-z0-9_./%+,:=@-]+")
CONTEXTUAL_PACKAGE_REFS = (
    re.compile(
        r"`[A-Z0-9_.-]+/[A-Z0-9_.-]+\x40[A-Z0-9._/-]+`",
        re.IGNORECASE,
    ),
    re.compile(
        r"\buses:\s*[A-Z0-9_.-]+/[A-Z0-9_.-]+"
        r"\x40[A-Z0-9._/-]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdependency:\s*[A-Z0-9_.-]+/[A-Z0-9_.-]+"
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
        r"https://cdn\.jsdelivr\.net/npm/"
        r"(?:\x40[A-Z0-9_.-]+/)?[A-Z0-9_.-]+\x40[A-Z0-9._-]+",
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

ABSOLUTE_USER_HOME_PATH = re.compile(
    r"(?:(?<![A-Za-z0-9._:/-])(?:/Users|/home)/[\w.-]+"
    r"(?=[\\/]|$|[^\w.-])|"
    r"(?<![A-Za-z0-9._/\\-])[A-Za-z]:[\\/]+Users[\\/]+[\w.-]+"
    r"(?=[\\/]|$|[^\w.-])|"
    r"(?<![A-Za-z0-9._/-])(?-i:/root)(?=/|$))",
    re.IGNORECASE,
)

PATTERNS = {
    "absolute user-home path": ABSOLUTE_USER_HOME_PATH,
    "environment-specific GitHub repository": re.compile(
        r"(?:github\.com/|raw\.githubusercontent\.com/|api\.github\.com/repos/)"
        r"minghsuy/"
        r"(?!lazy-hsa(?:\.git)?(?=[^A-Za-z0-9_.-]|$))[A-Za-z0-9_.-]+",
        re.IGNORECASE,
    ),
}

PUBLIC_GITHUB_SSH_CLONE = re.compile(
    rf"(?<![A-Z0-9._%+-])(?:"
    rf"{re.escape(SSH_COMMAND)}://git\x40github\.com/"
    rf"|git\x40github\.com:)"
    rf"{re.escape(PUBLIC_REPOSITORY)}(?:\.git)?"
    r"(?![A-Z0-9._/-])",
    re.IGNORECASE,
)


def allowed_reference_spans(text: str) -> tuple[re.Match[str], ...]:
    """Return package, action, and image references that use ``@`` safely."""
    return tuple(
        match for pattern in CONTEXTUAL_PACKAGE_REFS for match in pattern.finditer(text)
    ) + tuple(PUBLIC_GITHUB_SSH_CLONE.finditer(text))


def is_within_allowed_reference(
    match: re.Match[str],
    allowed_refs: tuple[re.Match[str], ...],
) -> bool:
    """Return whether a match is wholly contained in a recognized reference."""
    return any(ref.start() <= match.start() and ref.end() >= match.end() for ref in allowed_refs)


def span_is_within_allowed_reference(
    start: int,
    end: int,
    allowed_refs: tuple[re.Match[str], ...],
) -> bool:
    """Return whether offsets are wholly contained in a recognized reference."""
    return any(ref.start() <= start and ref.end() >= end for ref in allowed_refs)


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


class ShellRedirectionToken(str):
    """Tagged bounded redirection whose raw quote provenance is known."""


def mark_simple_shell_redirections(
    line: str,
) -> tuple[str, dict[str, ShellRedirectionToken]]:
    """Replace unquoted attached redirections with collision-free markers."""
    markers: dict[str, ShellRedirectionToken] = {}
    marker_index = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal marker_index
        while True:
            marker_index += 1
            marker = f"__lazy_hsa_simple_redirection_{marker_index}__"
            if marker not in line and marker not in markers:
                markers[marker] = ShellRedirectionToken(match.group(0))
                return marker

    return SIMPLE_SHELL_REDIRECTION.sub(replace, line), markers


def shell_tokens(line: str) -> list[str]:
    """Tokenize shell punctuation while retaining a fail-closed fallback."""

    def replace_ansi_c_quote(match: re.Match[str]) -> str:
        body = match.group(1)
        if "\\" in body:
            with suppress(UnicodeDecodeError, UnicodeEncodeError):
                body = codecs.decode(body.encode("ascii"), "unicode_escape")
        return shlex.quote(body)

    normalized = ANSI_C_QUOTED.sub(replace_ansi_c_quote, line)
    normalized = BARE_WINDOWS_SHELL_PATH.sub(
        lambda match: shlex.quote(match.group(1)),
        normalized,
    )
    normalized, redirection_markers = mark_simple_shell_redirections(normalized)
    try:
        lexer = shlex.shlex(normalized, posix=True, punctuation_chars=";&|()")
        lexer.commenters = ""
        lexer.whitespace_split = True
        return [redirection_markers.get(token, token) for token in lexer]
    except ValueError:
        return [
            redirection_markers.get(token, token)
            for token in re.findall(r"&&|\|\||[;&|()]|[^\s;&|()]+", normalized)
        ]


def config_tokens(line: str) -> list[str]:
    """Tokenize one OpenSSH config line while honoring comments."""
    try:
        lexer = shlex.shlex(line, posix=True)
        lexer.commenters = "#"
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return []


def config_key_values(line: str) -> tuple[str, list[str]] | None:
    """Normalize optional equals spacing in one OpenSSH or Git assignment."""
    assignment = CONFIG_ASSIGNMENT.fullmatch(line)
    if assignment is not None:
        values = config_tokens(assignment.group(2))
        return assignment.group(1), values
    tokens = config_tokens(line)
    return (tokens[0], tokens[1:]) if tokens else None


def openssh_match_exec_commands(text: str) -> list[str]:
    """Extract commands from line-anchored OpenSSH ``Match exec`` criteria."""
    commands: list[str] = []
    for line in text.splitlines():
        tokens = config_tokens(line)
        if not tokens or tokens[0].lower() != "match":
            continue
        index = 1
        while index < len(tokens):
            criterion_token = tokens[index].removeprefix("!")
            criterion, separator, attached_value = criterion_token.partition("=")
            criterion = criterion.lower()
            if criterion in OPENSSH_MATCH_FLAGS:
                index += 1
                continue
            if criterion not in OPENSSH_MATCH_VALUE_CRITERIA:
                break
            if separator:
                value = attached_value
                consumed = 1
            elif index + 1 < len(tokens) and tokens[index + 1] == "=":
                if index + 2 >= len(tokens):
                    break
                value = tokens[index + 2]
                consumed = 3
            elif index + 1 < len(tokens):
                value = tokens[index + 1]
                consumed = 2
            else:
                break
            if criterion == "exec":
                commands.append(value)
            index += consumed
    return commands


def executable_line(line: str) -> str:
    """Return an inline YAML command scalar or the original shell line."""
    match = INLINE_YAML_COMMAND.fullmatch(line)
    if match is None:
        return line
    value = match.group(1)
    if not value or value.startswith(("|", ">", "[", "{")):
        return ""
    if value.startswith(("'", '"')):
        tokens = config_tokens(value)
        return tokens[0] if len(tokens) == 1 else ""
    return value


def parse_openssh_arguments(
    tokens: list[str],
    command_index: int,
    options_with_argument: set[str],
    long_options_with_argument: set[str] | None = None,
    *,
    options_after_operands: bool = False,
    flags_out: list[str] | None = None,
    long_flags: set[str] | None = None,
    option_events_out: list[tuple[str, str | None]] | None = None,
) -> tuple[list[tuple[str, int]], list[tuple[str, str]]]:
    """Parse operands and option arguments for a shell command."""
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
            if token.startswith("--") and long_options_with_argument is not None:
                name, separator, attached_argument = token[2:].partition("=")
                known_long_options = long_options_with_argument | (long_flags or set())
                if long_flags is not None and name not in known_long_options:
                    prefix_matches = {
                        option for option in known_long_options if option.startswith(name)
                    }
                    if len(prefix_matches) == 1:
                        name = prefix_matches.pop()
                if name in long_options_with_argument:
                    if separator:
                        option_arguments.append((name, attached_argument))
                        if option_events_out is not None:
                            option_events_out.append((name, attached_argument))
                    elif index + 1 < len(tokens) and tokens[index + 1] not in {
                        ";",
                        "&&",
                        "||",
                        "|",
                        "(",
                        ")",
                    }:
                        index += 1
                        option_arguments.append((name, tokens[index]))
                        if option_events_out is not None:
                            option_events_out.append((name, tokens[index]))
                    elif option_events_out is not None:
                        option_events_out.append((name, None))
                elif flags_out is not None:
                    flags_out.append(name)
                    if option_events_out is not None:
                        option_events_out.append((name, None))
                elif option_events_out is not None:
                    option_events_out.append((name, None))
                index += 1
                continue
            option_cluster = token[1:]
            for option_index, option in enumerate(option_cluster):
                if option not in options_with_argument:
                    if flags_out is not None:
                        flags_out.append(option)
                    if option_events_out is not None:
                        option_events_out.append((option, None))
                    continue
                attached_argument = option_cluster[option_index + 1 :]
                if attached_argument:
                    option_arguments.append((option, attached_argument))
                    if option_events_out is not None:
                        option_events_out.append((option, attached_argument))
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
                    if option_events_out is not None:
                        option_events_out.append((option, tokens[index]))
                elif option_events_out is not None:
                    option_events_out.append((option, None))
                break
            index += 1
            continue
        if not options_after_operands:
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
            index += 1
            break
        if wrapper == "env" and token == "-":
            index += 1
            continue
        if not token.startswith("-") or token == "-":
            break
        if token.startswith("--"):
            name, separator, _ = token[2:].partition("=")
            if wrapper == "env":
                name = resolved_git_long_option(token, ENV_LONG_OPTIONS) or name
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
    if wrapper == "env":
        while index < len(prefix):
            name, separator, _ = prefix[index].partition("=")
            if not separator or not name:
                break
            index += 1
    return index


def consume_process_wrapper(prefix: list[str], index: int, wrapper: str) -> int | None:
    """Return the command position after a bounded process wrapper grammar."""
    index += 1
    if wrapper == "busybox":
        return index
    if wrapper == "nohup":
        if index < len(prefix) and prefix[index] == "--":
            return index + 1
        return None if index < len(prefix) else index
    if wrapper == "nice":
        while index < len(prefix) and prefix[index].startswith("-"):
            token = prefix[index]
            if token == "--":
                return index + 1
            if token in {"--help", "--version"}:
                return None
            name, separator, _ = token.partition("=")
            if name in {"--adjustment", "-n"} and not separator:
                if index + 1 >= len(prefix):
                    return None
                index += 1
            index += 1
        return index
    if wrapper == "time":
        while index < len(prefix) and prefix[index] in {"-p", "--"}:
            index += 1
        return index
    while index < len(prefix) and prefix[index].startswith("-"):
        token = prefix[index]
        if token == "--":
            index += 1
            break
        if token in {"--help", "--version"}:
            return None
        name, separator, _ = token.partition("=")
        if name in {"--kill-after", "--signal"} and not separator:
            if index + 1 >= len(prefix):
                return None
            index += 1
        elif token.startswith("-") and not token.startswith("--"):
            for option_index, option in enumerate(token[1:]):
                if option not in {"k", "s"}:
                    continue
                if not token[option_index + 2 :] and index + 1 >= len(prefix):
                    return None
                if not token[option_index + 2 :]:
                    index += 1
                break
        index += 1
    return index + 1 if index < len(prefix) else None


def shell_command_prefix(tokens: list[str], command_index: int) -> list[str]:
    """Return tokens between the nearest shell boundary and a command."""
    start = command_index - 1
    while start >= 0 and tokens[start] not in SSH_COMMAND_PREDECESSORS:
        start -= 1
    return tokens[start + 1 : command_index]


def without_simple_shell_redirections(tokens: list[str]) -> list[str]:
    """Remove only raw, unquoted bounded redirections from a command prefix."""
    return [token for token in tokens if not isinstance(token, ShellRedirectionToken)]


def resolved_git_long_option(argument: str, options: set[str]) -> str | None:
    """Resolve one unambiguous Git long-option abbreviation."""
    if not argument.startswith("--"):
        return None
    name = argument[2:].partition("=")[0]
    matches = [option for option in options if option.startswith(name)]
    return matches[0] if len(matches) == 1 else None


def git_config_key_is_valid(key: str) -> bool:
    """Recognize Git's command-line config section and variable grammar."""
    section, separator, _ = key.partition(".")
    variable = key.rpartition(".")[2]
    return bool(
        separator
        and re.fullmatch(r"[A-Za-z0-9-]+", section)
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", variable)
    )


def git_last_boolean_option(
    arguments: list[str],
    *,
    short: str,
    enabled: str,
    disabled: str,
    short_options_with_argument: set[str] | None = None,
    long_options_with_argument: set[str] | None = None,
    enabled_takes_value: bool = False,
) -> bool:
    """Return a Git boolean option's last-option-wins state."""
    short_options_with_argument = short_options_with_argument or set()
    long_options_with_argument = long_options_with_argument or set()
    state = False
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            break
        if argument.startswith("-") and not argument.startswith("--"):
            cluster = argument[1:]
            option_index = 0
            while option_index < len(cluster):
                option = cluster[option_index]
                if option == short:
                    state = True
                if option in short_options_with_argument:
                    if option_index + 1 == len(cluster):
                        index += 1
                    break
                option_index += 1
            index += 1
            continue
        value_option = resolved_git_long_option(argument, long_options_with_argument)
        if value_option is not None:
            if "=" not in argument:
                index += 1
            index += 1
            continue
        resolved = resolved_git_long_option(argument, {enabled, disabled})
        if resolved == enabled:
            state = True
            if enabled_takes_value and "=" not in argument:
                index += 1
        elif resolved == disabled:
            state = False
        index += 1
    return state


def git_has_short_flag_before_terminator(arguments: list[str], flag: str) -> bool:
    """Return whether a repeated short flag occurs before ``--``."""
    for argument in arguments:
        if argument == "--":
            break
        if (
            argument.startswith("-")
            and not argument.startswith("--")
            and argument[1:]
            and set(argument[1:]) == {flag}
        ):
            return True
    return False


def git_operands_may_use_transport(operands: list[tuple[str, int]]) -> bool:
    """Return whether parsed Git operands select a network-bearing operation."""
    if not operands:
        return False
    values = [operand for operand, _ in operands]
    subcommand = values[0].rsplit("/", maxsplit=1)[-1]
    arguments = values[1:]
    if subcommand in GIT_REMOTE_SUBCOMMANDS - {"archive"}:
        return True
    if subcommand == "archive":
        return git_last_boolean_option(
            arguments,
            short="",
            enabled="remote",
            disabled="no-remote",
            long_options_with_argument={
                "add-file",
                "add-virtual-file",
                "exec",
                "format",
                "mtime",
                "output",
                "prefix",
            },
            enabled_takes_value=True,
        )
    if subcommand == "remote":
        while arguments and (
            (
                arguments[0].startswith("-")
                and not arguments[0].startswith("--")
                and set(arguments[0][1:]) == {"v"}
            )
            or resolved_git_long_option(arguments[0], {"verbose", "no-verbose"}) is not None
        ):
            arguments = arguments[1:]
        if not arguments:
            return False
        operation, operation_arguments = arguments[0], arguments[1:]
        if operation in {"prune", "update"}:
            return True
        if operation == "show":
            return not git_has_short_flag_before_terminator(operation_arguments, "n")
        if operation == "add":
            return git_last_boolean_option(
                operation_arguments,
                short="f",
                enabled="fetch",
                disabled="no-fetch",
                short_options_with_argument={"m", "t"},
                long_options_with_argument={"master", "track"},
            )
        if operation == "set-head":
            return git_last_boolean_option(
                operation_arguments,
                short="a",
                enabled="auto",
                disabled="no-auto",
            )
        return False
    if subcommand == "submodule":
        while arguments and arguments[0] in {"-q", "--quiet"}:
            arguments = arguments[1:]
        return bool(arguments and arguments[0] in {"add", "update"})
    return False


def ssh_is_in_command_position(tokens: list[str], command_index: int) -> bool:
    """Recognize shell prefixes without mistaking ordinary prose for a command."""
    prefix = without_simple_shell_redirections(shell_command_prefix(tokens, command_index))
    if not prefix:
        return True
    index = 0
    while index < len(prefix) and SHELL_ASSIGNMENT.fullmatch(prefix[index]):
        index += 1
    while index < len(prefix):
        wrapper = prefix[index].rsplit("/", maxsplit=1)[-1]
        if wrapper in SSH_COMMAND_WRAPPERS:
            next_index = consume_wrapper_options(prefix, index, wrapper)
        elif wrapper in PROCESS_COMMAND_WRAPPERS:
            next_index = consume_process_wrapper(prefix, index, wrapper)
        else:
            return False
        if next_index is None:
            return False
        index = next_index
        while index < len(prefix) and SHELL_ASSIGNMENT.fullmatch(prefix[index]):
            index += 1
    return True


def inline_environment_from_prefix(prefix_tokens: list[str]) -> dict[str, str]:
    """Model bounded shell assignments and GNU env mutations before a command."""
    inline_environment: dict[str, str] = {}
    inside_env_prefix = False
    env_options_enabled = False
    prefix_index = 0
    while prefix_index < len(prefix_tokens):
        prefix_token = prefix_tokens[prefix_index]
        if prefix_token in {";", "&&", "||", "|", "(", ")"}:
            break
        name, separator, value = prefix_token.partition("=")
        if prefix_token.rsplit("/", maxsplit=1)[-1] == "env":
            inside_env_prefix = True
            env_options_enabled = True
        elif inside_env_prefix:
            resolved_env_option = (
                resolved_git_long_option(prefix_token, ENV_LONG_OPTIONS)
                if env_options_enabled
                else None
            )
            if env_options_enabled and prefix_token == "--":
                env_options_enabled = False
            elif (
                env_options_enabled and prefix_token == "-"
            ) or resolved_env_option == "ignore-environment":
                inline_environment.clear()
            elif resolved_env_option == "unset":
                environment_name = value if separator else ""
                if not environment_name and prefix_index + 1 < len(prefix_tokens):
                    prefix_index += 1
                    environment_name = prefix_tokens[prefix_index]
                inline_environment.pop(environment_name, None)
            elif resolved_env_option in WRAPPER_LONG_OPTIONS_WITH_ARGUMENT["env"]:
                if not separator and prefix_index + 1 < len(prefix_tokens):
                    prefix_index += 1
            elif (
                env_options_enabled
                and prefix_token.startswith("-")
                and not prefix_token.startswith("--")
            ):
                cluster = prefix_token[1:]
                cluster_index = 0
                while cluster_index < len(cluster):
                    option = cluster[cluster_index]
                    if option == "i":
                        inline_environment.clear()
                    elif option == "u":
                        environment_name = cluster[cluster_index + 1 :]
                        if not environment_name and prefix_index + 1 < len(prefix_tokens):
                            prefix_index += 1
                            environment_name = prefix_tokens[prefix_index]
                        inline_environment.pop(environment_name, None)
                        break
                    elif option in WRAPPER_SHORT_OPTIONS_WITH_ARGUMENT["env"]:
                        if cluster_index + 1 == len(cluster) and prefix_index + 1 < len(
                            prefix_tokens
                        ):
                            prefix_index += 1
                        break
                    cluster_index += 1
            elif separator and name:
                inline_environment[name] = value
        elif separator:
            assignment_name = name.removesuffix("+")
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", assignment_name):
                if name.endswith("+"):
                    inline_environment[assignment_name] = (
                        inline_environment.get(assignment_name, "") + value
                    )
                else:
                    inline_environment[assignment_name] = value
        prefix_index += 1
    return inline_environment


def command_with_inline_environment(command: str, environment: dict[str, str]) -> str:
    """Prefix a nested command with a shell-safe representation of inline env."""
    if not environment:
        return command
    assignments = " ".join(
        nested_shell_quote(f"{name}={value}") for name, value in environment.items()
    )
    return f"env -- {assignments} {command}"


def nested_shell_quote(value: str) -> str:
    """Quote one synthetic token without embedding control-line boundaries."""
    if any(character in value for character in "\n\r\t\v\f"):
        escaped = value.encode("unicode_escape").decode("ascii").replace("'", r"\'")
        return f"$'{escaped}'"
    return shlex.quote(value)


def nested_shell_join(arguments: list[str]) -> str:
    """Join synthetic tokens while keeping control characters token-local."""
    return " ".join(nested_shell_quote(argument) for argument in arguments)


def env_split_with_inline_environment(command: str, environment: dict[str, str]) -> str:
    """Re-enter env parsing after applying state established before ``-S``."""
    if not environment:
        return f"env {command}"
    assignments = " ".join(
        nested_shell_quote(f"{name}={value}") for name, value in environment.items()
    )
    return f"env -- {assignments} env {command}"


def split_env_string(command: str, environment: dict[str, str]) -> list[str] | None:
    """Parse GNU env ``-S`` quoting, escapes, and atomic variable expansion."""
    arguments: list[str] = []
    current: list[str] = []
    index = 0
    quote: str | None = None
    argument_started = False
    escapes = {
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "#": "#",
        "$": "$",
        '"': '"',
        "'": "'",
        "\\": "\\",
    }

    def finish_argument() -> None:
        nonlocal argument_started
        if argument_started:
            arguments.append("".join(current))
            current.clear()
            argument_started = False

    while index < len(command):
        character = command[index]
        if quote == "'":
            if character == "'":
                quote = None
            elif character == "\\" and index + 1 < len(command):
                escaped = command[index + 1]
                if escaped not in {"'", "\\"}:
                    current.append(character)
                    index += 1
                    continue
                current.append(escaped)
                index += 2
                continue
            else:
                current.append(character)
            index += 1
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif character == quote:
                quote = None
            else:
                current.append(character)
            argument_started = True
            index += 1
            continue
        if character == "\\":
            if index + 1 >= len(command):
                return None
            escaped = command[index + 1]
            if escaped == "c":
                if quote == '"':
                    return None
                break
            if escaped == "_":
                if quote == '"':
                    current.append(" ")
                    argument_started = True
                else:
                    finish_argument()
                index += 2
                continue
            if escaped not in escapes:
                return None
            current.append(escapes[escaped])
            argument_started = True
            index += 2
            continue
        if character == "$":
            if not command.startswith("${", index):
                return None
            closing_brace = command.find("}", index + 2)
            if closing_brace < 0:
                return None
            name = command[index + 2 : closing_brace]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                return None
            value = environment.get(name, "")
            current.append(value)
            argument_started = argument_started or name in environment
            index = closing_brace + 1
            continue
        if quote is None and character in " \t\n\r\v\f":
            finish_argument()
            index += 1
            continue
        if quote is None and character == "#" and not argument_started:
            break
        current.append(character)
        argument_started = True
        index += 1
    if quote is not None:
        return None
    finish_argument()
    return arguments


def env_split_string_commands(tokens: list[str], command_index: int) -> list[tuple[str, int]]:
    """Return GNU env split strings and the token ending each option argument."""
    commands: list[tuple[str, int]] = []
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
        if options_enabled and token == "-":
            index += 1
            continue
        if options_enabled and token.startswith("--"):
            option = resolved_git_long_option(token, ENV_LONG_OPTIONS)
            _, separator, argument = token.partition("=")
            if option in WRAPPER_LONG_OPTIONS_WITH_ARGUMENT["env"]:
                if not separator:
                    if index + 1 >= len(tokens):
                        break
                    index += 1
                    argument = tokens[index]
                if option == "split-string":
                    commands.append((argument, index))
                    break
            index += 1
            continue
        if options_enabled and token.startswith("-"):
            cluster = token[1:]
            for option_index, option in enumerate(cluster):
                if option not in WRAPPER_SHORT_OPTIONS_WITH_ARGUMENT["env"]:
                    continue
                argument = cluster[option_index + 1 :]
                if not argument:
                    if index + 1 >= len(tokens):
                        return commands
                    index += 1
                    argument = tokens[index]
                if option == "S":
                    commands.append((argument, index))
                    return commands
                break
            index += 1
            continue
        name, separator, _ = token.partition("=")
        if separator and name:
            break
        break
    return commands


def command_token_sequences(text: str):
    """Yield commands plus bounded shell and ``env -S`` command strings."""
    pending = [text]
    inspected: set[str] = set()
    while pending:
        current = pending.pop()
        if current in inspected:
            continue
        inspected.add(current)
        for line in current.replace("\\\n", " ").splitlines():
            line = executable_line(line)
            if not line:
                continue
            tokens = shell_tokens(line)
            yield tokens
            for index, token in enumerate(tokens):
                executable = token.rsplit("/", maxsplit=1)[-1]
                if not ssh_is_in_command_position(tokens, index):
                    continue
                if executable in SHELL_COMMANDS:
                    _, option_arguments = parse_openssh_arguments(
                        tokens,
                        index,
                        SHELL_OPTIONS_WITH_ARGUMENT,
                        SHELL_LONG_OPTIONS_WITH_ARGUMENT,
                    )
                    inline_environment = inline_environment_from_prefix(
                        without_simple_shell_redirections(shell_command_prefix(tokens, index))
                    )
                    pending.extend(
                        command_with_inline_environment(argument, inline_environment)
                        for option, argument in option_arguments
                        if option == "c"
                    )
                elif executable == "env":
                    for split_command, end_index in env_split_string_commands(tokens, index):
                        inline_environment = inline_environment_from_prefix(
                            without_simple_shell_redirections(
                                shell_command_prefix(tokens, index) + tokens[index : end_index + 1]
                            )
                        )
                        expansion_environment = inline_environment_from_prefix(
                            without_simple_shell_redirections(shell_command_prefix(tokens, index))
                        )
                        split_arguments = split_env_string(split_command, expansion_environment)
                        if split_arguments is None:
                            continue
                        trailing_arguments: list[str] = []
                        for argument in tokens[end_index + 1 :]:
                            if argument in {";", "&&", "||", "|", "(", ")"}:
                                break
                            trailing_arguments.append(argument)
                        expanded_command = nested_shell_join(split_arguments + trailing_arguments)
                        pending.append(
                            env_split_with_inline_environment(expanded_command, inline_environment)
                        )
                elif executable == GIT_COMMAND:
                    global_option_events: list[tuple[str, str | None]] = []
                    operands, _ = parse_openssh_arguments(
                        tokens,
                        index,
                        GIT_GLOBAL_OPTIONS_WITH_ARGUMENT,
                        GIT_GLOBAL_LONG_OPTIONS_WITH_ARGUMENT,
                        long_flags=set(),
                        option_events_out=global_option_events,
                    )
                    if git_operands_may_use_transport(operands):
                        inline_environment = inline_environment_from_prefix(
                            without_simple_shell_redirections(shell_command_prefix(tokens, index))
                        )

                        global_has_ssh_command = False
                        global_ssh_command: str | None = None
                        global_config_failed = False
                        for option, argument in global_option_events:
                            if option == "config-env" and argument is None:
                                global_config_failed = True
                                continue
                            if argument is None:
                                continue
                            if option == "c":
                                key, separator, value = argument.partition("=")
                                if not git_config_key_is_valid(key):
                                    global_config_failed = True
                                    continue
                                if key.lower() == "core.sshcommand":
                                    global_has_ssh_command = True
                                    global_ssh_command = value if separator else ""
                            elif option == "config-env":
                                key, separator, environment_name = argument.partition("=")
                                if (
                                    not separator
                                    or not git_config_key_is_valid(key)
                                    or not environment_name
                                    or environment_name not in inline_environment
                                ):
                                    global_config_failed = True
                                    continue
                                if key.lower() == "core.sshcommand":
                                    global_has_ssh_command = True
                                    global_ssh_command = inline_environment[environment_name]

                        clone_ssh_commands: list[str] = []
                        clone_config_failed = False
                        if operands and operands[0][0].rsplit("/", maxsplit=1)[-1] == "clone":
                            clone_option_events: list[tuple[str, str | None]] = []
                            parse_openssh_arguments(
                                tokens,
                                operands[0][1],
                                GIT_REMOTE_OPTIONS_WITH_ARGUMENT["clone"],
                                GIT_REMOTE_LONG_OPTIONS_WITH_ARGUMENT["clone"],
                                options_after_operands=True,
                                long_flags=GIT_REMOTE_LONG_FLAGS["clone"],
                                option_events_out=clone_option_events,
                            )
                            for option, argument in clone_option_events:
                                if option == "no-config":
                                    clone_ssh_commands.clear()
                                    clone_config_failed = False
                                    continue
                                if option not in {"c", "config"} or argument is None:
                                    continue
                                key, separator, value = argument.partition("=")
                                if not git_config_key_is_valid(key):
                                    clone_config_failed = True
                                    continue
                                if key.lower() == "core.sshcommand":
                                    clone_ssh_commands.append(value if separator else "")
                        if global_config_failed or clone_config_failed:
                            continue
                        if global_has_ssh_command:
                            if global_ssh_command is not None:
                                pending.append(global_ssh_command)
                        else:
                            pending.extend(clone_ssh_commands[-1:])


def uri_host(destination: str, scheme: str) -> str | None:
    """Return a URI hostname for the expected scheme."""
    try:
        parsed = urlsplit(destination)
        if parsed.scheme.lower() != scheme or not parsed.hostname:
            return None
        return parsed.hostname
    except ValueError:
        return None


def has_absolute_user_home_file_uri(text: str) -> bool:
    """Recognize local ``file`` URIs whose path is an absolute user home."""
    prefix = FILE_URI_SCHEME + ":"
    lowered = text.lower()
    search_from = 0
    while (start := lowered.find(prefix, search_from)) >= 0:
        search_from = start + len(prefix)
        if start and (text[start - 1].isalnum() or text[start - 1] in "_+.-/:\\"):
            continue
        end = search_from
        while end < len(text) and not text[end].isspace() and text[end] not in "<>'\"`":
            end += 1
        candidate = text[start:end].rstrip(".,;!?)}")
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            continue
        if parsed.scheme.lower() != FILE_URI_SCHEME or parsed.netloc.lower() not in {
            "",
            "localhost",
        }:
            continue
        path = unquote(parsed.path)
        windows_path = re.match(r"^/?[A-Za-z]:[\\/]", path)
        if windows_path is not None and path.startswith("/"):
            path = path[1:]
        elif windows_path is None and not path.startswith("/"):
            continue
        if ABSOLUTE_USER_HOME_PATH.search(path):
            return True
    return False


def has_disallowed_remote_uri(
    text: str,
    allowed_refs: tuple[re.Match[str], ...] | None = None,
) -> bool:
    """Reject non-example remote URIs independently of command parsing."""
    allowed_refs = allowed_reference_spans(text) if allowed_refs is None else allowed_refs
    lowered = text.lower()
    for scheme in STANDALONE_REMOTE_URI_SCHEMES:
        prefix = scheme + "://"
        search_from = 0
        while (start := lowered.find(prefix, search_from)) >= 0:
            search_from = start + len(prefix)
            if start and (text[start - 1].isalnum() or text[start - 1] in "+.-"):
                continue
            end = search_from
            while end < len(text) and not text[end].isspace() and text[end] not in "<>'\"`":
                end += 1
            candidate = text[start:end].rstrip(".,;!?)}")
            if span_is_within_allowed_reference(
                start,
                start + len(candidate),
                allowed_refs,
            ):
                continue
            host = uri_host(candidate, scheme)
            if host is not None and remote_host_is_disallowed(host):
                return True
    return False


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


def split_forward_fields(specification: str) -> list[str]:
    """Split an SSH forwarding specification without splitting bracketed IPv6."""
    fields: list[str] = []
    current: list[str] = []
    bracket_depth = 0
    for character in specification:
        if character == "[":
            bracket_depth += 1
        elif character == "]" and bracket_depth:
            bracket_depth -= 1
        if character == ":" and bracket_depth == 0:
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    fields.append("".join(current))
    return fields


def forwarding_target_host(specification: str) -> str | None:
    """Extract only the target host from ``-L``/``-R`` forwarding syntax."""
    fields = split_forward_fields(specification)
    if len(fields) < 3:
        return None
    target = fields[-2]
    return target[1:-1] if target.startswith("[") and target.endswith("]") else target


def openssh_forward_target(value: str) -> str | None:
    """Extract a target from a LocalForward/RemoteForward config value."""
    parts = value.split()
    if len(parts) >= 2:
        return endpoint_authority_host(parts[1])
    return forwarding_target_host(value)


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
    if option in {"L", "R"}:
        host = forwarding_target_host(argument)
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
    if normalized_key in {"localforward", "remoteforward"}:
        host = openssh_forward_target(value)
        return [host] if host is not None else []
    if normalized_key == "proxycommand" and inspect_proxy_command:
        return proxy_command_hosts(value)
    return []


def has_disallowed_openssh_config_endpoint(text: str) -> bool:
    """Reject endpoint-bearing OpenSSH directives on actual config lines."""
    endpoint_options = {
        "hostname": "W",
        "localforward": "L",
        "proxyjump": "J",
        "remoteforward": "R",
    }
    for line in text.splitlines():
        parsed = config_key_values(line)
        if parsed is None:
            continue
        key, values = parsed
        normalized_key = key.lower()
        if not values:
            continue
        if normalized_key == "proxycommand":
            value = " ".join(shlex.quote(part) for part in values)
            hosts = proxy_command_hosts(value)
        elif (option := endpoint_options.get(normalized_key)) is not None:
            value = " ".join(values)
            if option in {"L", "R"}:
                host = openssh_forward_target(value)
                hosts = [host] if host is not None else []
            else:
                hosts = option_endpoint_hosts(option, value, False)
        else:
            continue
        if any(remote_host_is_disallowed(host) for host in hosts):
            return True
    return False


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
        for tokens in command_token_sequences(current):
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


def has_disallowed_git_scp_url(text: str) -> bool:
    """Reject scp-like remotes in line-anchored Git URL assignments."""
    for line in text.splitlines():
        raw_assignment = RAW_GIT_URL_ASSIGNMENT.fullmatch(line)
        if raw_assignment is not None:
            raw_value = raw_assignment.group(1).lstrip()
            if raw_value.startswith(("'", '"')):
                raw_value = raw_value[1:]
            if git_value_is_windows_path(raw_value):
                continue
        parsed = config_key_values(line)
        if parsed is None:
            continue
        key, values = parsed
        if key.lower().rsplit(".", maxsplit=1)[-1] not in {"url", "pushurl"}:
            continue
        if not values:
            continue
        remote = values[0]
        if git_scp_remote_is_disallowed(remote):
            return True
    return False


def git_value_is_windows_path(value: str) -> bool:
    """Recognize absolute Windows drive paths without hiding scp-like URLs."""
    return bool(re.match(r"^[A-Za-z]:[\\/]", value))


def git_scp_remote_is_disallowed(remote: str) -> bool:
    """Classify one Git remote while preserving Windows drive-local paths."""
    if PUBLIC_GITHUB_SSH_CLONE.fullmatch(remote) or git_value_is_windows_path(remote):
        return False
    host = scp_remote_host(remote)
    return bool(host is not None and remote.rpartition(":")[2] and remote_host_is_disallowed(host))


def git_config_key_value_remotes(key: str, value: str) -> list[str]:
    """Extract endpoint values and URL rewrite bases from one Git config pair."""
    lowered = key.lower()
    if lowered.rsplit(".", maxsplit=1)[-1] in {"url", "pushurl"}:
        return [value]
    for suffix in (".insteadof", ".pushinsteadof"):
        if lowered.startswith("url.") and lowered.endswith(suffix):
            return [key[4 : -len(suffix)]]
    return []


def git_config_assignment_remotes(argument: str) -> list[str]:
    """Extract endpoint-bearing values from a Git ``-c key=value`` argument."""
    key, separator, value = argument.partition("=")
    return git_config_key_value_remotes(key, value) if separator else []


def git_command_remote_operands(tokens: list[str], command_index: int) -> list[str]:
    """Return positional remote operands for network-bearing Git subcommands."""
    global_operands, global_option_arguments = parse_openssh_arguments(
        tokens,
        command_index,
        GIT_GLOBAL_OPTIONS_WITH_ARGUMENT,
        GIT_GLOBAL_LONG_OPTIONS_WITH_ARGUMENT,
    )
    config_remotes = [
        remote
        for option, argument in global_option_arguments
        if option == "c"
        for remote in git_config_assignment_remotes(argument)
    ]
    if not global_operands:
        return config_remotes
    subcommand, subcommand_index = global_operands[0]
    subcommand = subcommand.rsplit("/", maxsplit=1)[-1]
    if subcommand in GIT_REMOTE_SUBCOMMANDS:
        parsed_flags: list[str] = []
        operands, option_arguments = parse_openssh_arguments(
            tokens,
            subcommand_index,
            GIT_REMOTE_OPTIONS_WITH_ARGUMENT[subcommand],
            GIT_REMOTE_LONG_OPTIONS_WITH_ARGUMENT[subcommand],
            options_after_operands=True,
            flags_out=parsed_flags,
            long_flags=GIT_REMOTE_LONG_FLAGS[subcommand],
        )
        explicit_remote_options = {
            "archive": {"remote"},
            "push": {"repo"},
        }.get(subcommand, set())
        explicit_remotes = [
            argument for option, argument in option_arguments if option in explicit_remote_options
        ]
        config_remotes.extend(
            remote
            for option, argument in option_arguments
            if option in {"c", "config"}
            for remote in git_config_assignment_remotes(argument)
        )
        if explicit_remotes:
            return config_remotes + explicit_remotes
        if subcommand == "archive":
            return config_remotes
        if subcommand == "fetch" and any(flag in {"m", "multiple"} for flag in parsed_flags):
            return config_remotes + [operand for operand, _ in operands]
        return config_remotes + ([operands[0][0]] if operands else [])
    if subcommand == "remote":
        parsed_flags = []
        operands, _ = parse_openssh_arguments(
            tokens,
            subcommand_index,
            GIT_REMOTE_MANAGEMENT_OPTIONS_WITH_ARGUMENT,
            GIT_REMOTE_MANAGEMENT_LONG_OPTIONS_WITH_ARGUMENT,
            options_after_operands=True,
            flags_out=parsed_flags,
            long_flags=GIT_REMOTE_MANAGEMENT_LONG_FLAGS,
        )
        if len(operands) >= 3 and operands[0][0] in {"add", "set-url"}:
            if any(flag not in GIT_REMOTE_MANAGEMENT_LONG_FLAGS for flag in parsed_flags):
                return [operand for operand, _ in operands[1:]]
            return [operands[2][0]]
    if subcommand == "submodule":
        parsed_flags = []
        operands, _ = parse_openssh_arguments(
            tokens,
            subcommand_index,
            GIT_SUBMODULE_OPTIONS_WITH_ARGUMENT,
            GIT_SUBMODULE_LONG_OPTIONS_WITH_ARGUMENT,
            options_after_operands=True,
            flags_out=parsed_flags,
            long_flags=GIT_SUBMODULE_LONG_FLAGS,
        )
        if len(operands) >= 2 and operands[0][0] == "add":
            if any(flag not in GIT_SUBMODULE_LONG_FLAGS for flag in parsed_flags):
                return config_remotes + [operand for operand, _ in operands[1:]]
            return config_remotes + [operands[1][0]]
        if len(operands) >= 3 and operands[0][0] == "set-url":
            return config_remotes + [operands[2][0]]
    if subcommand == "config":
        parsed_flags = []
        operands, _ = parse_openssh_arguments(
            tokens,
            subcommand_index,
            GIT_CONFIG_OPTIONS_WITH_ARGUMENT,
            GIT_CONFIG_LONG_OPTIONS_WITH_ARGUMENT,
            options_after_operands=True,
            flags_out=parsed_flags,
            long_flags=GIT_CONFIG_LONG_FLAGS,
        )
        if len(operands) >= 2:
            if any(flag not in GIT_CONFIG_LONG_FLAGS for flag in parsed_flags):
                return config_remotes + [operand for operand, _ in operands]
            key_index = 1 if operands[0][0] in {"add", "replace-all", "set"} else 0
            if len(operands) > key_index + 1:
                config_remotes.extend(
                    git_config_key_value_remotes(operands[key_index][0], operands[key_index + 1][0])
                )
    return config_remotes


def has_disallowed_git_command_scp_url(text: str) -> bool:
    """Reject scp-like endpoints passed to a Git command in shell position."""
    for tokens in command_token_sequences(text):
        for index, token in enumerate(tokens):
            if token.rsplit("/", maxsplit=1)[-1] != GIT_COMMAND or not ssh_is_in_command_position(
                tokens, index
            ):
                continue
            if any(
                git_scp_remote_is_disallowed(remote)
                for remote in git_command_remote_operands(tokens, index)
            ):
                return True
    return False


def rsync_remote_host(operand: str) -> str | None:
    """Extract a host from an rsync URI or legacy ``[user@]host:path`` operand."""
    uri_destination = uri_host(operand, "rsync")
    if uri_destination is not None:
        return uri_destination
    if "://" in operand:
        return None
    return scp_remote_host(operand)


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
    for tokens in command_token_sequences(text):
        for index, token in enumerate(tokens):
            if token.rsplit("/", maxsplit=1)[-1] != SSH_COMMAND:
                continue
            in_command_position = ssh_is_in_command_position(tokens, index)
            if not in_command_position:
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
            destination, _ = operands[0]
            uri_destination = uri_host(destination, "ssh")
            host = (
                uri_destination
                if uri_destination is not None
                else endpoint_authority_host(destination)
            )
            if host is None or not remote_host_is_disallowed(host):
                continue
            if uri_destination is not None or HOSTLIKE_SSH_DESTINATION.fullmatch(host):
                return True
            # A line-start transport plus a single-label first operand is valid
            # executable syntax even when later arguments read like prose. Text
            # discussing that syntax must establish a prose context before the
            # command token rather than relying on terminal punctuation.
            if in_command_position and SINGLE_LABEL_SSH_DESTINATION.fullmatch(host):
                return True
    return False


def has_scp_command_with_remote(text: str) -> bool:
    """Reject non-example remote operands in shell SCP command position."""
    for tokens in command_token_sequences(text):
        for index, token in enumerate(tokens):
            if token.rsplit("/", maxsplit=1)[-1] != SCP_COMMAND:
                continue
            in_command_position = ssh_is_in_command_position(tokens, index)
            if not in_command_position:
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
    for tokens in command_token_sequences(text):
        for index, token in enumerate(tokens):
            if token.rsplit("/", maxsplit=1)[-1] != SFTP_COMMAND:
                continue
            in_command_position = ssh_is_in_command_position(tokens, index)
            if not in_command_position:
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
            destination, _ = operands[0]
            host = sftp_remote_host(destination)
            if host is None or not remote_host_is_disallowed(host):
                continue
            if HOSTLIKE_SSH_DESTINATION.fullmatch(host):
                return True
            if SINGLE_LABEL_SSH_DESTINATION.fullmatch(host) and in_command_position:
                return True
    return False


def has_rsync_command_with_remote(text: str) -> bool:
    """Reject non-example remote operands in shell rsync command position."""
    for tokens in command_token_sequences(text):
        for index, token in enumerate(tokens):
            if token.rsplit("/", maxsplit=1)[-1] != RSYNC_COMMAND:
                continue
            in_command_position = ssh_is_in_command_position(tokens, index)
            if not in_command_position:
                continue
            operands, option_arguments = parse_openssh_arguments(
                tokens,
                index,
                RSYNC_OPTIONS_WITH_ARGUMENT,
                RSYNC_LONG_OPTIONS_WITH_ARGUMENT,
                options_after_operands=True,
            )
            if any(
                remote_host_is_disallowed(host)
                for option, argument in option_arguments
                if option in {"e", "rsh"}
                for host in proxy_command_hosts(argument)
            ):
                return True
            for operand, _ in operands:
                host = rsync_remote_host(operand)
                if host is not None and remote_host_is_disallowed(host):
                    return True
    return False


def has_disallowed_openssh_match_exec(text: str) -> bool:
    """Reject private endpoints in active OpenSSH ``Match exec`` commands."""
    for command in openssh_match_exec_commands(text):
        if any(remote_host_is_disallowed(host) for host in proxy_command_hosts(command)):
            return True
        if (
            has_disallowed_remote_uri(command)
            or has_scp_command_with_remote(command)
            or has_sftp_command_with_remote(command)
            or has_rsync_command_with_remote(command)
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
    decoded = [
        data.decode("utf-8", errors="replace"),
        data.decode("latin-1"),
    ]
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
    if "absolute user-home path" not in categories and has_absolute_user_home_file_uri(text):
        categories.append("absolute user-home path")
    allowed_refs = allowed_reference_spans(text)
    if (
        has_disallowed_user_at_host_identifier(text, allowed_refs)
        or has_disallowed_remote_uri(text, allowed_refs)
        or has_disallowed_git_scp_url(text)
        or has_disallowed_git_command_scp_url(text)
        or has_disallowed_openssh_config_endpoint(text)
        or has_disallowed_openssh_match_exec(text)
        or has_ssh_command_without_user(text)
        or has_scp_command_with_remote(text)
        or has_sftp_command_with_remote(text)
        or has_rsync_command_with_remote(text)
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
