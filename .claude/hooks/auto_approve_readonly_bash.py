#!/usr/bin/env python3
"""Auto-approve compound Bash commands when every segment is independently safe.

Hook for Claude Code PreToolUse. Reads stdin JSON describing a Bash tool call,
splits the command into shell segments (`;`, `&&`, `||`, `|`), extracts the
leading command token from each, and approves the call only when every
segment's leading token is in a known read-only / safe set AND no hard-deny
pattern matches anywhere in the command.

Conservative by design: when the parser cannot prove safety (subshells,
heredocs, unknown tokens, deny-pattern hits), exit silently so Claude Code's
normal permission flow takes over. The hook never blocks; it only adds
positive auto-approvals on top of the existing allow/ask/deny rules.
"""

from __future__ import annotations

import json
import re
import sys

# Read-only utilities. Mirrors Claude Code's built-in auto-allow set
# (READONLY_COMMANDS / READONLY_NOARGS / COMMAND_ALLOWLIST) plus tools we
# explicitly allow at the project level (jq, yq, awk, fc-list, etc.).
SAFE_COMMANDS = {
    # Core read-only
    "cal",
    "uptime",
    "cat",
    "head",
    "tail",
    "wc",
    "stat",
    "strings",
    "hexdump",
    "od",
    "nl",
    "id",
    "uname",
    "free",
    "df",
    "du",
    "locale",
    "groups",
    "nproc",
    "basename",
    "dirname",
    "realpath",
    "cut",
    "paste",
    "tr",
    "column",
    "tac",
    "rev",
    "fold",
    "expand",
    "unexpand",
    "fmt",
    "comm",
    "cmp",
    "numfmt",
    "readlink",
    "diff",
    "true",
    "false",
    "sleep",
    "which",
    "type",
    "expr",
    "test",
    "getconf",
    "seq",
    "tsort",
    "pr",
    "echo",
    "printf",
    "ls",
    "cd",
    "find",
    "pwd",
    "whoami",
    "alias",
    # Auto-allowed with safe flags
    "xargs",
    "file",
    "sed",
    "sort",
    "man",
    "help",
    "netstat",
    "ps",
    "base64",
    "grep",
    "egrep",
    "fgrep",
    "sha256sum",
    "sha1sum",
    "md5sum",
    "tree",
    "date",
    "hostname",
    "info",
    "lsof",
    "pgrep",
    "tput",
    "ss",
    "fd",
    "fdfind",
    "aki",
    "rg",
    "jq",
    "uniq",
    "history",
    "arch",
    "ifconfig",
    "pyright",
    # Project-level read-only additions
    "yq",
    "awk",
    "less",
    "more",
    "env",
    "printenv",
    "command",
    "getent",
    "fc-list",
    "fc-match",
    "pdftotext",
    "pandoc",
}

# Tools where ANY first-arg is read-only — git, gh, docker, etc.
# Used when the leading command itself is too coarse (e.g. `git` writes too).
SAFE_SUBCOMMANDS = {
    "git": {
        "status",
        "log",
        "diff",
        "show",
        "blame",
        "branch",
        "tag",
        "remote",
        "ls-files",
        "ls-remote",
        "ls-tree",
        "rev-parse",
        "describe",
        "reflog",
        "shortlog",
        "cat-file",
        "for-each-ref",
        "worktree",
        "stash",
    },
    "gh": {"pr", "issue", "run", "workflow", "repo", "release", "auth"},
    "docker": {"ps", "images", "logs", "inspect"},
    "kubectl": {"get", "describe"},
    "hf": {
        "auth",
        "download",
        "cache",
        "spaces",
        "skills",
        "env",
        "version",
        "--version",
        "--help",
    },
    "codex": {"--help", "--version"},
    "ruff": {"check", "format", "--help", "--version"},
}

# Patterns that must NEVER auto-approve, even if leading tokens look safe.
# Aligned with the `deny` and `ask` lists in .claude/settings.json. Keep
# in sync if those lists change.
HARD_DENY = [
    re.compile(r"\bsudo\b"),
    re.compile(r"curl\s+[^|]*\|\s*(?:sh|bash)\b"),
    re.compile(r"wget\s+[^|]*\|\s*(?:sh|bash)\b"),
    re.compile(r"\bgit\s+push\b.*--force"),
    re.compile(r"\bgit\s+push\b.*-f\b"),
    re.compile(r"\bgit\s+push\b.*--force-with-lease"),
    re.compile(r"\bgit\s+reset\b.*--hard"),
    re.compile(r"\bgit\s+clean\b"),
    re.compile(r"\bgit\s+filter-(branch|repo)\b"),
    re.compile(r"\bgit\s+branch\s+-D\b"),
    re.compile(r"\bgit\s+update-ref\s+-d\b"),
    re.compile(r"\bgit\s+rebase\s+-i\b"),
    re.compile(r"\bgit\s+tag\s+-d\b"),
    re.compile(r"\bgh\s+pr\s+merge\b"),
    re.compile(r"\bgh\s+pr\s+close\b"),
    re.compile(r"\bgh\s+issue\s+close\b"),
    re.compile(r"\bgh\s+release\b"),
    re.compile(r"\bgh\s+repo\s+delete\b"),
    re.compile(r"\bgh\s+api\s+-X\s+(POST|PUT|PATCH|DELETE)"),
    re.compile(r"\bhf\s+repo\s+delete\b"),
    re.compile(r"\bhf\s+cache\s+delete\b"),
    re.compile(r"\bhf\s+upload\b"),
    re.compile(r"\bhf\s+repo\s+create\b"),
    re.compile(r"\bhf\s+repo\s+tag\b"),
    re.compile(r"\bhf\s+jobs\s+(run|cancel|uv)\b"),
    re.compile(r"\bhf\s+auth\s+login\b"),
    re.compile(r"\brm\s+-rf?\b"),
    re.compile(r"\brmdir\b"),
]

# Bail out if any of these appear: subshells, command substitution, heredocs,
# process substitution, here-strings. Too easy to misparse.
UNSAFE_FEATURES = re.compile(r"\$\(|`|<\(|>\(|<<<|<<")

# Shell separators we split on. Order matters: longer tokens first so `&&` is
# not split as `&` `&`.
SEGMENT_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")

# Strip `cd … &&` / env-var / timeout prefixes and yield the actual command.
PREFIX_STRIP = re.compile(
    r"^(?:"
    r"(?:[A-Z_][A-Z0-9_]*=\S+\s+)+"  # ENV=val ...
    r"|cd\s+\S+\s*&&\s*"  # cd dir &&
    r"|timeout\s+\S+\s+"  # timeout 30 ...
    r")*"
)
LEAD_TOKEN = re.compile(r"^(\S+)")
# Strip redirects so they don't pollute token extraction.
REDIRECT_RE = re.compile(r"\s*\d?(?:>>?|<)\s*&?\d*\s*\S*")


def is_safe_segment(seg: str) -> bool:
    seg = seg.strip().lstrip("(").rstrip(")").strip()
    if not seg:
        return True

    # Strip redirects (2>/dev/null, > file, >&2, etc.)
    seg_clean = REDIRECT_RE.sub("", seg).strip()
    seg_clean = PREFIX_STRIP.sub("", seg_clean).strip()
    if not seg_clean:
        return True

    m = LEAD_TOKEN.match(seg_clean)
    if not m:
        return False
    cmd = m.group(1)
    cmd_base = cmd.rsplit("/", 1)[-1]  # /usr/bin/ls -> ls

    if cmd_base in SAFE_COMMANDS:
        return True

    if cmd_base in SAFE_SUBCOMMANDS:
        rest = seg_clean[m.end() :].strip().split()
        if not rest:
            return True  # bare invocation prints help, harmless
        return rest[0] in SAFE_SUBCOMMANDS[cmd_base]

    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    if data.get("tool_name") != "Bash":
        return 0

    cmd = data.get("tool_input", {}).get("command", "")
    if not isinstance(cmd, str) or not cmd.strip():
        return 0

    if UNSAFE_FEATURES.search(cmd):
        return 0

    for pat in HARD_DENY:
        if pat.search(cmd):
            return 0

    segments = SEGMENT_SPLIT.split(cmd)
    if not segments or not all(is_safe_segment(s) for s in segments):
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "auto-approved: all segments are read-only / safe",
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
