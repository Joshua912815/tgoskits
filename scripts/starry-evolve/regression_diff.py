#!/usr/bin/env python3
"""Compare current StarryOS test results against stored baseline.

Usage:
    python3 regression_diff.py --repo-root /path/to/tgoskits [--format json|markdown]
"""

import argparse
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


def run_quick_test(repo_root: Path, target: str):
    """Run a quick test and return pass/fail."""
    cmd = ["cargo", "xtask", "starry", "test", "qemu", "--target", target]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def load_baseline(repo_root: Path):
    """Load the stored baseline."""
    baseline_path = repo_root / "scripts" / "starry-evolve" / "baseline.json"
    if not baseline_path.exists():
        return None
    try:
        return json.loads(baseline_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def format_markdown(comparison):
    lines = ["# StarryOS Regression Report\n"]

    if comparison.get("error"):
        lines.append(f"**Error**: {comparison['error']}")
        return "\n".join(lines)

    baseline_exists = comparison.get("baseline_exists", False)
    lines.append(f"**Baseline exists**: {'Yes' if baseline_exists else 'No'}")
    lines.append("")

    results = comparison.get("results", [])
    lines.append("| Target | Baseline | Current | Status |")
    lines.append("|--------|----------|---------|--------|")
    for r in results:
        status = "REGRESSION" if r.get("regression") else ("IMPROVEMENT" if r.get("improvement") else "SAME")
        baseline_status = "PASS" if r.get("baseline_passed") else ("FAIL" if r.get("baseline_passed") is False else "N/A")
        current_status = "PASS" if r.get("current_passed") else "FAIL"
        lines.append(f"| {r['target']} | {baseline_status} | {current_status} | {status} |")
    lines.append("")

    regressions = [r for r in results if r.get("regression")]
    improvements = [r for r in results if r.get("improvement")]

    if regressions:
        lines.append("## Regressions")
        for r in regressions:
            lines.append(f"- **{r['target']}**: was PASS, now FAIL")
        lines.append("")

    if improvements:
        lines.append("## Improvements")
        for r in improvements:
            lines.append(f"- **{r['target']}**: was FAIL, now PASS")
        lines.append("")

    if not regressions and not improvements:
        lines.append("**No regressions or improvements detected.**")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compare current test results against baseline")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else find_repo_root()
    if not repo_root:
        print("Error: Cannot find repo root. Use --repo-root.", file=sys.stderr)
        sys.exit(1)

    baseline = load_baseline(repo_root)
    targets = ["riscv64", "aarch64"]

    comparison = {
        "baseline_exists": baseline is not None,
        "results": [],
    }

    for target in targets:
        current_passed = run_quick_test(repo_root, target)
        entry = {
            "target": target,
            "current_passed": current_passed,
        }

        if baseline:
            # Find matching baseline entry
            baseline_entry = next((b for b in baseline if b.get("target") == target), None)
            if baseline_entry:
                baseline_passed = baseline_entry.get("success", False)
                entry["baseline_passed"] = baseline_passed
                entry["regression"] = baseline_passed and not current_passed
                entry["improvement"] = not baseline_passed and current_passed
            else:
                entry["baseline_passed"] = None
        else:
            comparison["error"] = "No baseline found. Run test_runner.py --update-baseline first."

        comparison["results"].append(entry)

    if args.format == "json":
        print(json.dumps(comparison, indent=2))
    else:
        print(format_markdown(comparison))


if __name__ == "__main__":
    main()
