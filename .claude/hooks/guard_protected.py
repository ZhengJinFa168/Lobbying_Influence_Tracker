#!/usr/bin/env python3
"""PreToolUse guard: writes to contract, linter, test, CI and guardrail files need the user's approval.

Edit/Write/MultiEdit/NotebookEdit are checked by path (case-insensitively: macOS filesystems are). Bash is checked
heuristically: a command that names a protected path and contains a write-like token (redirect, sed -i, mv, rm,
git checkout, shutil, ...) is sent for approval, and so are tool commands that rewrite config on their own
(tach sync, pre-commit autoupdate, agy without --mode plan, ...). It is a tripwire for agents, not a sandbox.
Returns permissionDecision "ask"; anything else passes through.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import sys

# Repo-relative glob patterns (fnmatch: `*` also matches `/`). Compared casefolded.
PROTECTED = {
    "graph contract": ["neo4j/schema.cypher", "docs/IMPLEMENTATION_PLAN.md", "docs/neo4j_graph_schema.md"],
    "linter config": ["tach.toml", ".pre-commit-config.yaml", "requirements-dev.txt"],
    "tests": ["tests/*", "*/tests/*", "test_*.py", "*/test_*.py", "*_test.py", "conftest.py", "*/conftest.py"],
    "CI": [".github/*"],
    "agent guardrails": ["CLAUDE.md", ".claude/settings.json", ".claude/settings.local.json", ".claude/hooks/*",
                         ".claude/agents/*"],
}

# Substrings (casefolded) that identify a protected path inside a shell command.
BASH_NEEDLES = [
    "schema.cypher", "implementation_plan.md", "neo4j_graph_schema.md",
    "tach.toml", ".pre-commit-config", "requirements-dev.txt",
    "test_", "_test.py", "conftest.py",
    ".github", "claude.md", ".claude/settings", ".claude/hooks", ".claude/agents",
]
TESTS_DIR = re.compile(r"(^|[\s/'\"])tests\b")
# Strip things that look like `>` but are not redirects: fd duplication, /dev/null, arrows, <placeholders>.
NOT_A_REDIRECT = re.compile(r"\d*>&\d|\d*>>?\s*/dev/null|->|=>|<[^<>\s]+>")
WRITE_TOKEN = re.compile(
    r">|\btee\b|\b(sed|perl)\b[^|;&]*\s-[a-z]*i"
    r"|\b(mv|cp|rm|rmdir|touch|truncate|ln|chmod|install|dd|rsync|patch|mkdir|unlink)\b"
    r"|\bgit\b(\s+-\S+(\s+[^-\s]\S*)?)*\s+(checkout|restore|reset|rm|mv|apply|stash|clean)\b"
    r"|\bgit\b[^|;&]*\s--output\b"
    r"|open\(|write_text|write_bytes|\bshutil\b|\bos\.(remove|rename|replace|unlink)|\.unlink\(|\.rename\(|\.replace\("
)
# Commands that rewrite protected files without naming them.
SELF_WRITING = re.compile(
    r"\btach\s+(sync|init|mod|install)\b|\bpre-commit\s+(autoupdate|migrate-config|install|uninstall)\b"
    r"|--dangerously-skip-permissions"
)
AGY = re.compile(r"(^|[\s;&|(])agy\s")
AGY_READ_ONLY = re.compile(r"--mode[\s=]+plan\b")


def category(rel: str) -> str | None:
    rel = rel.casefold()
    for name, patterns in PROTECTED.items():
        if any(fnmatch.fnmatchcase(rel, p.casefold()) for p in patterns):
            return name
    return None


def relpath(path: str, root: str) -> str | None:
    full = os.path.realpath(os.path.join(root, path))
    root = os.path.realpath(root)
    if full.casefold() != root.casefold() and not full.casefold().startswith(root.casefold() + os.sep):
        return None
    return full[len(root) + 1:]


def ask(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


def check_bash(cmd: str) -> None:
    low = cmd.casefold()
    if SELF_WRITING.search(low):
        ask("Command can rewrite tach.toml, pre-commit config or bypass permissions. Needs the user's approval.")
    if AGY.search(low) and not AGY_READ_ONLY.search(low):
        ask("agy without --mode plan can edit files. Needs the user's approval.")
    hits = [n for n in BASH_NEEDLES if n in low] + (["tests/"] if TESTS_DIR.search(low) else [])
    if hits and WRITE_TOKEN.search(NOT_A_REDIRECT.sub("", low)):
        ask(f"Protected path in a command that may write ({', '.join(hits)}). "
            "Contracts, linter config, tests, CI and guardrails change only with the user's approval.")


def main() -> None:
    try:
        event = json.load(sys.stdin)
        args = event.get("tool_input") or {}
        if not isinstance(args, dict):
            raise ValueError("tool_input is not an object")
    except (ValueError, AttributeError):
        ask("guard_protected: could not parse hook input; approve manually")
    root = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    tool = event.get("tool_name", "")

    if tool == "Bash":
        check_bash(str(args.get("command", "")))
        return

    path = args.get("file_path") or args.get("notebook_path")
    if not path:
        return
    rel = relpath(str(path), root)
    if rel is None:
        return
    cat = category(rel)
    if cat:
        ask(f"{rel} is a protected file ({cat}). It changes only with the user's approval (see CLAUDE.md).")


if __name__ == "__main__":
    main()
