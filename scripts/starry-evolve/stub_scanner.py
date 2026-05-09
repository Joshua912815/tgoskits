#!/usr/bin/env python3
"""Scan StarryOS kernel source for stub and incomplete implementations.

Searches for patterns like warn!("dummy"), todo!(), unimplemented!(),
hardcoded Ok(0) returns, and other indicators of incomplete code.

Usage:
    python3 stub_scanner.py --repo-root /path/to/tgoskits [--format json|markdown]
"""

import argparse
import json
import os
import re
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


PATTERNS = [
    {
        "id": "warn_dummy",
        "regex": r'warn!\("([Dd]ummy[^"]*)"\)',
        "severity": "high",
        "description": "Dummy/stub warning",
    },
    {
        "id": "warn_unimplemented",
        "regex": r'warn!\("([Uu]nimplemented[^"]*)"\)',
        "severity": "high",
        "description": "Unimplemented syscall warning",
    },
    {
        "id": "todo_macro",
        "regex": r"todo!\(\)",
        "severity": "critical",
        "description": "todo!() macro (will panic at runtime)",
    },
    {
        "id": "unimplemented_macro",
        "regex": r"unimplemented!\(\)",
        "severity": "critical",
        "description": "unimplemented!() macro (will panic at runtime)",
    },
    {
        "id": "fixme_comment",
        "regex": r"FIXME|TODO|HACK|XXX",
        "severity": "low",
        "description": "FIXME/TODO/HACK comment",
    },
    {
        "id": "ok_zero_return",
        "regex": r"return\s+Ok\(\s*0\s*\)",
        "severity": "medium",
        "description": "Hardcoded Ok(0) return (no-op stub)",
    },
    {
        "id": "enosys_return",
        "regex": r"ENOSYS",
        "severity": "high",
        "description": "ENOSYS error return (syscall not implemented)",
    },
    {
        "id": "empty_fn_body",
        "regex": r"pub fn \w+\([^)]*\)\s*->\s*[^{]*\{\s*\}",
        "severity": "critical",
        "description": "Empty function body",
    },
]

# File extensions to scan
SCAN_EXTENSIONS = {".rs"}


def scan_file(filepath: Path, patterns):
    """Scan a single file for stub patterns."""
    findings = []
    try:
        lines = filepath.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return findings

    for i, line in enumerate(lines, 1):
        for pat in patterns:
            if re.search(pat["regex"], line):
                findings.append({
                    "file": str(filepath),
                    "line": i,
                    "pattern_id": pat["id"],
                    "severity": pat["severity"],
                    "description": pat["description"],
                    "content": line.strip(),
                })

    return findings


def scan_directory(kernel_dir: Path, patterns):
    """Scan all Rust files in the kernel directory."""
    all_findings = []
    for root, dirs, files in os.walk(kernel_dir):
        for fname in files:
            fpath = Path(root) / fname
            if fpath.suffix in SCAN_EXTENSIONS:
                all_findings.extend(scan_file(fpath, patterns))
    return all_findings


def format_markdown(findings, kernel_dir: Path):
    """Format findings as markdown."""
    # Group by severity
    by_severity = {"critical": [], "high": [], "medium": [], "low": []}
    for f in findings:
        by_severity[f["severity"]].append(f)

    lines = ["# StarryOS Kernel Stub Scanner Report\n"]
    lines.append(f"**Total findings**: {len(findings)}")
    lines.append(f"- Critical: {len(by_severity['critical'])}")
    lines.append(f"- High: {len(by_severity['high'])}")
    lines.append(f"- Medium: {len(by_severity['medium'])}")
    lines.append(f"- Low: {len(by_severity['low'])}")
    lines.append("")

    for severity in ("critical", "high", "medium", "low"):
        items = by_severity[severity]
        if not items:
            continue
        lines.append(f"## {severity.upper()}\n")
        for f in items:
            rel_path = f["file"].replace(str(kernel_dir) + "/", "")
            lines.append(f"- **{f['description']}** at `{rel_path}:{f['line']}`")
            lines.append(f"  ```")
            lines.append(f"  {f['content']}")
            lines.append(f"  ```")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Scan StarryOS kernel for stub implementations")
    parser.add_argument("--repo-root", type=str, default=None, help="Path to tgoskits repo root")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown", help="Output format")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else find_repo_root()
    if not repo_root:
        print("Error: Cannot find repo root. Use --repo-root.", file=sys.stderr)
        sys.exit(1)

    kernel_dir = repo_root / "os" / "StarryOS" / "kernel" / "src"
    if not kernel_dir.exists():
        print(f"Error: {kernel_dir} not found", file=sys.stderr)
        sys.exit(1)

    findings = scan_directory(kernel_dir, PATTERNS)

    if args.format == "json":
        print(json.dumps(findings, indent=2))
    else:
        print(format_markdown(findings, kernel_dir))


if __name__ == "__main__":
    main()
