#!/usr/bin/env python3
"""Build StarryOS for all supported architectures and report results.

Usage:
    python3 build_checker.py --repo-root /path/to/tgoskits [--archs riscv64,aarch64,x86_64,loongarch64] [--format json|markdown]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


ARCHS = ["riscv64", "aarch64", "x86_64", "loongarch64"]


def find_repo_root():
    d = Path.cwd()
    for _ in range(10):
        ct = d / "Cargo.toml"
        if ct.exists() and "[workspace]" in ct.read_text():
            return d
        d = d.parent
    return None


def build_arch(repo_root: Path, arch: str):
    """Build StarryOS for a specific architecture."""
    cmd = ["cargo", "xtask", "starry", "build", "--arch", arch]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=300,
        )
        return {
            "arch": arch,
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout,
            "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"arch": arch, "success": False, "exit_code": -1, "stdout": "", "stderr": "Build timed out (300s)"}
    except FileNotFoundError:
        return {"arch": arch, "success": False, "exit_code": -1, "stdout": "", "stderr": "cargo not found"}


def format_markdown(results):
    lines = ["# StarryOS Build Check Report\n"]
    lines.append("| Architecture | Status | Details |")
    lines.append("|-------------|--------|---------|")
    for r in results:
        status = "PASS" if r["success"] else "FAIL"
        details = ""
        if not r["success"]:
            # Extract key error from stderr
            stderr_lines = r["stderr"].strip().splitlines()
            errors = [l for l in stderr_lines if "error" in l.lower()]
            details = errors[-1][:80] if errors else "See stderr"
        lines.append(f"| {r['arch']} | {status} | {details} |")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Build StarryOS for all supported architectures")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--archs", type=str, default=None, help="Comma-separated arch list")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else find_repo_root()
    if not repo_root:
        print("Error: Cannot find repo root. Use --repo-root.", file=sys.stderr)
        sys.exit(1)

    archs = args.archs.split(",") if args.archs else ARCHS
    results = []
    for arch in archs:
        print(f"Building for {arch}...", file=sys.stderr)
        results.append(build_arch(repo_root, arch))

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        print(format_markdown(results))


if __name__ == "__main__":
    main()
