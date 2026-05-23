#!/usr/bin/env python3
"""Audit StarryOS syscall dispatch table and classify implementation status.

Parses os/StarryOS/kernel/src/syscall/mod.rs to extract all dispatched syscalls,
then classifies each as IMPLEMENTED, PARTIAL, STUB, or MISSING by examining
the handler function bodies.

Usage:
    python3 syscall_audit.py --repo-root /path/to/tgoskits [--format json|markdown]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


def find_repo_root():
    """Find repo root by looking for Cargo.toml with [workspace]."""
    d = Path.cwd()
    for _ in range(10):
        ct = d / "Cargo.toml"
        if ct.exists() and "[workspace]" in ct.read_text():
            return d
        d = d.parent
    return None


def parse_dispatch(mod_rs: Path):
    """Parse syscall/mod.rs to extract dispatch entries.

    Returns list of dicts: {sysno, handler, category, is_stub, is_arch_specific, line}
    """
    text = mod_rs.read_text()
    lines = text.splitlines()
    entries = []
    current_category = "unknown"

    # Category comments like: // fs ctl, // mm, // task management
    cat_pattern = re.compile(r"^\s*//\s+(.+)")
    # Match arm: Sysno::NAME => ...
    arm_pattern = re.compile(r"Sysno::(\w+)")
    # Alternation: Sysno::A | Sysno::B => ...
    multi_pattern = re.compile(r"((?:Sysno::\w+\s*\|\s*)+Sysno::\w+)\s*=>")
    # Handler call: sys_xxx(...)
    handler_re = re.compile(r"\s*(?:\{)?\s*(?:unsafe\s+)?(\w+)\(")
    # Direct return: => Ok(0) or => Err(...)
    return_re = re.compile(r"\s*(?:\{)?\s*(Ok\([^)]*\)|Err\([^)]*\))")
    # Dummy fd handler
    dummy_pattern = re.compile(r"sys_dummy_fd")
    # Arch gate
    arch_gate_pattern = re.compile(r"#\[cfg\(target_arch\s*=\s*\"(\w+)\"\)\]")

    i = 0
    current_arch = None
    while i < len(lines):
        line = lines[i]

        # Track category comments
        cat_match = cat_pattern.match(line)
        if cat_match and not line.strip().startswith("//!") and not line.strip().startswith("///"):
            cat_text = cat_match.group(1).strip().lower()
            if cat_text in (
                "fs ctl", "file ops", "fd ops", "io", "io mpx", "fs mount",
                "pipe", "event", "pidfd", "memfd", "fs stat", "mm",
                "task info", "task sched", "task ops", "task management",
                "signal", "sys", "sync", "time", "msg", "shm", "net",
                "signal file descriptors", "dummy fds",
            ):
                current_category = cat_text

        # Track arch gates
        arch_match = arch_gate_pattern.match(line.strip())
        if arch_match:
            current_arch = arch_match.group(1)
        elif line.strip() and not line.strip().startswith("#") and not line.strip().startswith("//"):
            current_arch = None

        # Find match arms
        # First check multi-arm pattern
        multi_match = multi_pattern.search(line)
        if multi_match:
            arm_str = multi_match.group(1)
            syscalls = arm_pattern.findall(arm_str)
            # Find the handler on the same or next line
            remaining = line[multi_match.end():]
            ret_match = return_re.search(remaining)
            hm = None if ret_match else handler_re.search(remaining)
            if not hm:
                # Check continuation
                if not ret_match and i + 1 < len(lines):
                    hm = handler_re.search(lines[i + 1])

            is_dummy = bool(dummy_pattern.search(line) or (hm and hm.group(1) == "sys_dummy_fd"))
            is_stub = bool(ret_match and "Ok(0)" in ret_match.group(1))

            for s in syscalls:
                entries.append({
                    "sysno": s,
                    "handler": hm.group(1) if hm else None,
                    "category": current_category,
                    "is_stub": is_stub or is_dummy,
                    "is_dummy_fd": is_dummy,
                    "is_arch_specific": current_arch,
                    "line": i + 1,
                })
            i += 1
            continue

        # Single arm
        for arm_match_obj in arm_pattern.finditer(line):
            sysno = arm_match_obj.group(1)
            # Skip if this is inside a multi-arm (already handled)
            if multi_match:
                continue
            remaining = line[arm_match_obj.end():]
            # Look for =>
            arrow_pos = remaining.find("=>")
            if arrow_pos == -1:
                continue
            after_arrow = remaining[arrow_pos + 2:]
            ret_match = return_re.search(after_arrow)
            hm = None if ret_match else handler_re.search(after_arrow)

            is_dummy = bool(dummy_pattern.search(after_arrow) or (hm and hm.group(1) == "sys_dummy_fd"))
            is_stub = bool(ret_match and "Ok(0)" in ret_match.group(1))

            entries.append({
                "sysno": sysno,
                "handler": hm.group(1) if hm else None,
                "category": current_category,
                "is_stub": is_stub or is_dummy,
                "is_dummy_fd": is_dummy,
                "is_arch_specific": current_arch,
                "line": i + 1,
            })

        i += 1

    return entries


def find_handler_definition(kernel_dir: Path, handler: str):
    """Find a Rust handler definition and extract its full brace-matched body."""
    pattern = re.compile(rf"\bfn\s+{re.escape(handler)}\b")
    for filepath in kernel_dir.rglob("*.rs"):
        try:
            content = filepath.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        match = pattern.search(content)
        if not match:
            continue
        brace_start = content.find("{", match.end())
        line = content[:match.start()].count("\n") + 1
        if brace_start == -1:
            return filepath, line, content[match.start():match.end()], "low"

        depth = 0
        end = None
        for idx in range(brace_start, len(content)):
            ch = content[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break
        if end is None:
            return filepath, line, content[match.start():], "low"
        return filepath, line, content[match.start():end], "high"
    return None, None, "", "low"


def summarize_evidence(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if any(token in stripped for token in ("warn!", "todo!()", "unimplemented!()", "return Ok(0)", "ENOSYS")):
            return stripped[:160]
    non_empty = [line.strip() for line in body.splitlines() if line.strip()]
    return non_empty[0][:160] if non_empty else ""


def check_handler_implementation(repo_root: Path, handler: str):
    """Check if a handler function has a real implementation vs stub.

    Returns a mapping with status, source location, evidence, and confidence.
    """
    if handler is None:
        return {
            "status": "STUB",
            "file": None,
            "line": None,
            "evidence": "no handler in dispatch arm",
            "confidence": "high",
        }

    kernel_dir = repo_root / "os" / "StarryOS" / "kernel" / "src" / "syscall"
    filepath, line, body, confidence = find_handler_definition(kernel_dir, handler)
    if filepath is None:
        return {
            "status": "STUB",
            "file": None,
            "line": None,
            "evidence": "handler definition not found",
            "confidence": "high",
        }

    stub_indicators = [
        'warn!("dummy',
        'warn!("Dummy',
        'warn!("Unimplemented',
        "todo!()",
        "unimplemented!()",
    ]
    status = "IMPLEMENTED"
    for indicator in stub_indicators:
        if indicator in body:
            status = "STUB"
            break
    if status == "IMPLEMENTED" and re.search(r"return\s+Ok\(\s*0\s*\)", body):
        status = "PARTIAL"
    return {
        "status": status,
        "file": str(filepath.relative_to(repo_root)),
        "line": line,
        "evidence": summarize_evidence(body),
        "confidence": confidence,
    }


def run_audit(repo_root: Path):
    """Run the full syscall audit."""
    mod_rs = repo_root / "os" / "StarryOS" / "kernel" / "src" / "syscall" / "mod.rs"
    if not mod_rs.exists():
        print(f"Error: {mod_rs} not found", file=sys.stderr)
        sys.exit(1)

    entries = parse_dispatch(mod_rs)

    results = {
        "implemented": [],
        "partial": [],
        "stub": [],
        "dummy_fd": [],
        "arch_specific": {},
        "by_category": {},
        "entries": [],
        "total_dispatched": len(entries),
    }

    for entry in entries:
        impl = check_handler_implementation(repo_root, entry["handler"])
        status = impl["status"]
        if entry["is_dummy_fd"]:
            status = "STUB"  # dummy_fd is a stub
            results["dummy_fd"].append(entry["sysno"])
        elif entry["is_stub"]:
            status = "STUB"

        entry["status"] = status
        entry["handler_file"] = impl["file"]
        entry["handler_line"] = impl["line"]
        entry["evidence"] = impl["evidence"]
        entry["confidence"] = impl["confidence"]
        cat = entry["category"]
        if cat not in results["by_category"]:
            results["by_category"][cat] = {"implemented": 0, "partial": 0, "stub": 0, "total": 0}
        results["by_category"][cat]["total"] += 1
        results["by_category"][cat][status.lower()] += 1

        if entry["is_arch_specific"]:
            arch = entry["is_arch_specific"]
            if arch not in results["arch_specific"]:
                results["arch_specific"][arch] = []
            results["arch_specific"][arch].append(entry["sysno"])

        if status == "IMPLEMENTED":
            results["implemented"].append(entry["sysno"])
        elif status == "PARTIAL":
            results["partial"].append(entry["sysno"])
        else:
            results["stub"].append(entry["sysno"])
        results["entries"].append(entry)

    return results


def format_markdown(results):
    """Format results as markdown."""
    lines = ["# StarryOS Syscall Audit Report\n"]
    lines.append(f"**Total dispatched**: {results['total_dispatched']}")
    lines.append(f"- Implemented: {len(results['implemented'])}")
    lines.append(f"- Partial: {len(results['partial'])}")
    lines.append(f"- Stub/Dummy: {len(results['stub'])}")
    lines.append(f"- Arch-specific: {sum(len(v) for v in results['arch_specific'].values())}")
    lines.append("")

    lines.append("## By Category\n")
    lines.append("| Category | Implemented | Partial | Stub | Total |")
    lines.append("|----------|-------------|---------|------|-------|")
    for cat, counts in sorted(results["by_category"].items()):
        lines.append(f"| {cat} | {counts['implemented']} | {counts['partial']} | {counts['stub']} | {counts['total']} |")
    lines.append("")

    if results["stub"]:
        lines.append("## Stub/Dummy Syscalls\n")
        for s in sorted(results["stub"]):
            entry = next(e for e in results["entries"] if e["sysno"] == s)
            loc = f" ({entry['handler_file']}:{entry['handler_line']})" if entry["handler_file"] else ""
            lines.append(f"- `{s}`{loc} — {entry['evidence']} [{entry['confidence']}]")
        lines.append("")

    if results["partial"]:
        lines.append("## Partial Implementations\n")
        for s in sorted(results["partial"]):
            entry = next(e for e in results["entries"] if e["sysno"] == s)
            loc = f" ({entry['handler_file']}:{entry['handler_line']})" if entry["handler_file"] else ""
            lines.append(f"- `{s}`{loc} — {entry['evidence']} [{entry['confidence']}]")
        lines.append("")

    if results["arch_specific"]:
        lines.append("## Arch-Specific Syscalls\n")
        for arch, syscalls in sorted(results["arch_specific"].items()):
            lines.append(f"### {arch}")
            for s in sorted(syscalls):
                lines.append(f"- `{s}`")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Audit StarryOS syscall dispatch table")
    parser.add_argument("--repo-root", type=str, default=None, help="Path to tgoskits repo root")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown", help="Output format")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else find_repo_root()
    if not repo_root:
        print("Error: Cannot find repo root. Use --repo-root.", file=sys.stderr)
        sys.exit(1)

    results = run_audit(repo_root)

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        print(format_markdown(results))


if __name__ == "__main__":
    main()
