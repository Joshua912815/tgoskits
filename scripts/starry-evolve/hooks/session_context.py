#!/usr/bin/env python3
"""SessionStart hook: load context for Claude Code sessions.

Reads the evolution journal and syscall status, outputs a summary
that Claude receives at session start.
"""

import json
import subprocess
import sys
from pathlib import Path


def find_repo_root():
    d = Path.cwd()
    for _ in range(10):
        ct = d / "Cargo.toml"
        if ct.exists() and "[workspace]" in ct.read_text():
            return d
        d = d.parent
    return None


def get_git_info(repo_root: Path):
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=5
        )
        recent = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=5
        )
        return {
            "branch": branch.stdout.strip(),
            "recent_commits": recent.stdout.strip(),
        }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"branch": "unknown", "recent_commits": ""}


def load_journal(evolve_dir: Path):
    journal_path = evolve_dir / "journal.md"
    if not journal_path.exists():
        return "No journal entries yet."
    try:
        lines = journal_path.read_text().strip().splitlines()
        # Last 50 lines
        return "\n".join(lines[-50:])
    except OSError:
        return "Could not read journal."


def load_status(evolve_dir: Path):
    import yaml
    status_path = evolve_dir / "syscall_status.yaml"
    if not status_path.exists():
        return "No status file yet."
    try:
        content = yaml.safe_load(status_path.read_text())
        syscalls = content.get("syscalls", [])
        if not syscalls:
            return "No syscalls tracked yet. Run /starry-analyze to populate."
        counts = {}
        for s in syscalls:
            st = s.get("status", "UNKNOWN")
            counts[st] = counts.get(st, 0) + 1
        parts = [f"{st}: {c}" for st, c in sorted(counts.items())]
        return f"Tracked syscalls: {len(syscalls)} total. " + ", ".join(parts)
    except Exception:
        return "Could not parse status file."


def main():
    repo_root = find_repo_root()
    if not repo_root:
        print("starry-evolve: Cannot find repo root.")
        return

    evolve_dir = repo_root / "scripts" / "starry-evolve"
    git_info = get_git_info(repo_root)
    journal = load_journal(evolve_dir)
    status = load_status(evolve_dir)

    print(f"[starry-evolve session context]")
    print(f"Branch: {git_info['branch']}")
    print(f"Status: {status}")
    print(f"")
    print(f"Recent commits:")
    print(git_info["recent_commits"])
    print(f"")
    print(f"Journal (last entries):")
    print(journal)


if __name__ == "__main__":
    main()
