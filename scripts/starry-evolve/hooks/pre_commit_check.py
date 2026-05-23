#!/usr/bin/env python3
"""Stop hook: check kernel code quality before session ends.

If files under os/StarryOS/kernel/ have been modified, verify that
cargo fmt and clippy pass. Warns on failure.
"""

import subprocess
import sys
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from verifier import REPORT_SCHEMA_VERSION, git_diff_hash


def find_repo_root():
    d = Path.cwd()
    for _ in range(10):
        ct = d / "Cargo.toml"
        if ct.exists() and "[workspace]" in ct.read_text():
            return d
        d = d.parent
    return None


def has_kernel_changes(repo_root: Path):
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10
        )
        changed = result.stdout.strip().splitlines()
        return any("os/StarryOS/kernel" in f for f in changed)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_fmt(repo_root: Path):
    try:
        result = subprocess.run(
            ["cargo", "fmt", "--check"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0, result.stdout + result.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, "fmt check timed out or cargo not found"


def check_clippy(repo_root: Path):
    try:
        result = subprocess.run(
            ["cargo", "xtask", "clippy", "--package", "starry-kernel"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=120
        )
        return result.returncode == 0, result.stdout[-500:] + result.stderr[-500:]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, "clippy check timed out"


def check_verifier_report(repo_root: Path):
    report_path = repo_root / "scripts" / "starry-evolve" / "reports" / "latest.json"
    if not report_path.exists():
        return False, "No verifier report found at scripts/starry-evolve/reports/latest.json"
    try:
        report = json.loads(report_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"Could not read verifier report: {exc}"
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        return False, f"Unsupported verifier report schema: {report.get('schema_version')}"
    if not report.get("run_id") or not report.get("syscall") or not report.get("case_results"):
        return False, "Latest verifier report is missing required identity or case fields"
    if not report.get("success"):
        return False, f"Latest verifier report is not successful: {report.get('run_id')}"
    current_hash = git_diff_hash(repo_root)
    if report.get("git_diff_hash") != current_hash:
        return False, "Latest verifier report does not match the current git diff hash"
    return True, ""


def main():
    repo_root = find_repo_root()
    if not repo_root:
        return

    if not has_kernel_changes(repo_root):
        return

    warnings = []

    fmt_ok, fmt_out = check_fmt(repo_root)
    if not fmt_ok:
        warnings.append("CARGO FMT: Unformatted code detected. Run `cargo fmt` before committing.")

    clippy_ok, clippy_out = check_clippy(repo_root)
    if not clippy_ok:
        warnings.append("CLIPPY: Issues found. Run `cargo xtask clippy --package starry-kernel` to see details.")

    verifier_ok, verifier_out = check_verifier_report(repo_root)
    if not verifier_ok:
        warnings.append(f"VERIFIER: {verifier_out}")

    if warnings:
        print("[starry-evolve pre-commit check]")
        for w in warnings:
            print(f"  WARNING: {w}")


if __name__ == "__main__":
    main()
