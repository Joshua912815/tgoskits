#!/usr/bin/env python3
"""Compare verifier case results against a case-level baseline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def find_repo_root() -> Path | None:
    d = Path.cwd()
    for _ in range(10):
        ct = d / "Cargo.toml"
        if ct.exists() and "[workspace]" in ct.read_text():
            return d
        d = d.parent
    return None


def case_key(case: dict) -> tuple[str, str, str]:
    return (case["syscall"], case["target"], case["case_id"])


def normalize_report_cases(report: dict) -> list[dict]:
    return [
        {
            "syscall": report["syscall"],
            "target": report["target"],
            "case_id": case["case_id"],
            "status": case["status"],
            "matched": case["matched"],
            "actual": case.get("actual"),
        }
        for case in report.get("case_results", [])
    ]


def compare_cases(baseline: dict, current_report: dict) -> dict:
    baseline_cases = {case_key(case): case for case in baseline.get("cases", [])}
    current_cases = {case_key(case): case for case in normalize_report_cases(current_report)}
    results = []
    for key in sorted(set(baseline_cases) | set(current_cases)):
        base = baseline_cases.get(key)
        curr = current_cases.get(key)
        base_passed = bool(base and base.get("matched"))
        curr_passed = bool(curr and curr.get("matched"))
        results.append(
            {
                "syscall": key[0],
                "target": key[1],
                "case_id": key[2],
                "baseline_status": base.get("status") if base else "MISSING",
                "current_status": curr.get("status") if curr else "MISSING",
                "regression": base_passed and not curr_passed,
                "improvement": (not base_passed) and curr_passed,
            }
        )
    return {
        "schema_version": 1,
        "baseline_source_report": baseline.get("source_report"),
        "current_report": current_report.get("run_id"),
        "baseline_diff_hash": baseline.get("git_diff_hash"),
        "current_diff_hash": current_report.get("git_diff_hash"),
        "results": results,
        "regressions": [row for row in results if row["regression"]],
        "improvements": [row for row in results if row["improvement"]],
    }


def format_markdown(comparison: dict) -> str:
    lines = ["# StarryOS Case-Level Regression Report", ""]
    lines.append(f"- Baseline report: `{comparison.get('baseline_source_report')}`")
    lines.append(f"- Current report: `{comparison.get('current_report')}`")
    lines.append("")
    lines.append("| Syscall | Target | Case | Baseline | Current | Status |")
    lines.append("|---------|--------|------|----------|---------|--------|")
    for row in comparison["results"]:
        status = "REGRESSION" if row["regression"] else ("IMPROVEMENT" if row["improvement"] else "SAME")
        lines.append(
            f"| `{row['syscall']}` | `{row['target']}` | `{row['case_id']}` | "
            f"{row['baseline_status']} | {row['current_status']} | {status} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare current verifier report against baseline")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--baseline", type=str, default=None)
    parser.add_argument("--current-report", type=str, default=None)
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else find_repo_root()
    if not repo_root:
        print("Error: Cannot find repo root. Use --repo-root.", file=sys.stderr)
        return 2
    baseline_path = Path(args.baseline) if args.baseline else repo_root / "scripts" / "starry-evolve" / "baseline.json"
    current_path = (
        Path(args.current_report)
        if args.current_report
        else repo_root / "scripts" / "starry-evolve" / "reports" / "latest.json"
    )
    if not baseline_path.exists():
        print(f"Error: baseline not found: {baseline_path}", file=sys.stderr)
        return 2
    if not current_path.exists():
        print(f"Error: current report not found: {current_path}", file=sys.stderr)
        return 2
    baseline = json.loads(baseline_path.read_text())
    current = json.loads(current_path.read_text())
    if "cases" not in baseline:
        print("Error: baseline is legacy arch-level format; update it with test_runner.py --update-baseline", file=sys.stderr)
        return 2
    comparison = compare_cases(baseline, current)
    if args.format == "json":
        print(json.dumps(comparison, indent=2, sort_keys=True))
    else:
        print(format_markdown(comparison))
    return 1 if comparison["regressions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
