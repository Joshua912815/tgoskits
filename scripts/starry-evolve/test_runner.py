#!/usr/bin/env python3
"""Run StarryOS QEMU tests and capture structured results.

Usage:
    python3 test_runner.py --repo-root /path/to/tgoskits [--target riscv64] [--update-baseline] [--format json|markdown]
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def find_repo_root():
    d = Path.cwd()
    for _ in range(10):
        ct = d / "Cargo.toml"
        if ct.exists() and "[workspace]" in ct.read_text():
            return d
        d = d.parent
    return None


def run_test(repo_root: Path, target: str):
    """Run StarryOS QEMU test for a specific target."""
    cmd = ["cargo", "xtask", "starry", "test", "qemu", "--target", target]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        success = result.returncode == 0

        # Parse test results from output
        test_output = {
            "target": target,
            "success": success,
            "exit_code": result.returncode,
            "timestamp": datetime.now().isoformat(),
            "output": output[-3000:] if len(output) > 3000 else output,
        }
        return test_output
    except subprocess.TimeoutExpired:
        return {
            "target": target,
            "success": False,
            "exit_code": -1,
            "timestamp": datetime.now().isoformat(),
            "output": "Test timed out (120s)",
        }
    except FileNotFoundError:
        return {
            "target": target,
            "success": False,
            "exit_code": -1,
            "timestamp": datetime.now().isoformat(),
            "output": "cargo not found",
        }


def format_markdown(results):
    lines = ["# StarryOS Test Run Report\n"]
    for r in results:
        status = "PASS" if r["success"] else "FAIL"
        lines.append(f"## {r['target']} — {status}\n")
        lines.append(f"- Timestamp: {r['timestamp']}")
        lines.append(f"- Exit code: {r['exit_code']}")
        if not r["success"]:
            # Show last few lines of output
            output_lines = r["output"].strip().splitlines()
            lines.append("- Last output:")
            for l in output_lines[-5:]:
                lines.append(f"  `{l}`")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run StarryOS QEMU tests")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--target", type=str, default="riscv64", help="Target architecture")
    parser.add_argument("--update-baseline", action="store_true", help="Update baseline.json with results")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else find_repo_root()
    if not repo_root:
        print("Error: Cannot find repo root. Use --repo-root.", file=sys.stderr)
        sys.exit(1)

    result = run_test(repo_root, args.target)
    results = [result]

    if args.update_baseline:
        baseline_path = repo_root / "scripts" / "starry-evolve" / "baseline.json"
        baseline_path.write_text(json.dumps(results, indent=2))
        print(f"Baseline updated: {baseline_path}", file=sys.stderr)

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        print(format_markdown(results))


if __name__ == "__main__":
    main()
