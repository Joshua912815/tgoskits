#!/usr/bin/env python3
"""Run Linux-vs-StarryOS syscall tests through the deterministic verifier."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from contract_schema import ContractError, contract_case_ids, load_contract
from verifier import build_pair_report, parse_jsonl_cases, report_filename


def find_repo_root() -> Path | None:
    d = Path.cwd()
    for _ in range(10):
        ct = d / "Cargo.toml"
        if ct.exists() and "[workspace]" in ct.read_text():
            return d
        d = d.parent
    return None


def default_contract_path(repo_root: Path, syscall: str) -> Path:
    return repo_root / "scripts" / "starry-evolve" / "contracts" / f"{syscall}.yaml"


def default_starry_command(target: str) -> str:
    return f"cargo xtask starry test qemu --target {target}"


def render_command(command: str, run_id: str) -> str:
    return command.replace("{run_id}", run_id)


def run_command(repo_root: Path, command: str, run_id: str, timeout: int) -> tuple[int, str]:
    env = os.environ.copy()
    env["STARRY_EVOLVE_RUN_ID"] = run_id
    result = subprocess.run(
        command,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        shell=True,
    )
    return result.returncode, result.stdout + result.stderr


def write_report(repo_root: Path, report: dict, linux_raw_output: str, starry_raw_output: str) -> Path:
    reports_dir = repo_root / "scripts" / "starry-evolve" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / report_filename(report)
    stem = path.with_suffix("")
    linux_log = stem.with_suffix(".linux.log")
    starry_log = stem.with_suffix(".starry.log")
    linux_log.write_text(linux_raw_output)
    starry_log.write_text(starry_raw_output)
    report["linux"]["raw_log_path"] = str(linux_log)
    report["starry"]["raw_log_path"] = str(starry_log)
    path.write_text(json.dumps(report, indent=2, sort_keys=True))
    (reports_dir / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    return path


def update_baseline(repo_root: Path, report: dict) -> None:
    baseline = {
        "schema_version": 1,
        "source_report": report["run_id"],
        "git_diff_hash": report["git_diff_hash"],
        "cases": [
            {
                "syscall": report["syscall"],
                "target": report["target"],
                "case_id": case["case_id"],
                "status": case["status"],
                "matched": case["matched"],
                "linux": case.get("linux"),
                "starry": case.get("starry"),
            }
            for case in report["case_results"]
        ],
    }
    (repo_root / "scripts" / "starry-evolve" / "baseline.json").write_text(
        json.dumps(baseline, indent=2, sort_keys=True)
    )


def format_markdown(report: dict, report_path: Path) -> str:
    status = "PASS" if report["success"] else "FAIL"
    lines = [
        "# StarryOS Pair Verifier Report",
        "",
        f"- Report: `{report_path}`",
        f"- Syscall: `{report['syscall']}`",
        f"- Target: `{report['target']}`",
        f"- Run ID: `{report['run_id']}`",
        f"- Status: **{status}**",
        f"- Linux exit code: `{report['linux']['exit_code']}`",
        f"- StarryOS exit code: `{report['starry']['exit_code']}`",
        f"- Diff hash: `{report['git_diff_hash']}`",
        f"- Linux raw log hash: `{report['linux']['raw_log_hash']}`",
        f"- StarryOS raw log hash: `{report['starry']['raw_log_hash']}`",
        "",
        "| Case | Status |",
        "|------|--------|",
    ]
    for case in report["case_results"]:
        lines.append(f"| `{case['case_id']}` | {case['status']} |")
    rejected = report["linux"]["rejected_lines"] + report["starry"]["rejected_lines"]
    if rejected:
        lines.extend(["", "## Rejected Output"])
        for item in rejected:
            lines.append(f"- {item}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Linux-vs-StarryOS syscall verifier")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--syscall", type=str, required=True)
    parser.add_argument("--contract", type=str, default=None)
    parser.add_argument("--target", type=str, default="riscv64")
    parser.add_argument("--source", type=str, default=None)
    parser.add_argument("--binary", type=str, default=None)
    parser.add_argument("--linux-raw-log", type=str, default=None)
    parser.add_argument("--linux-raw-log-exit-code", type=int, default=0)
    parser.add_argument("--starry-raw-log", type=str, default=None)
    parser.add_argument("--starry-raw-log-exit-code", type=int, default=0)
    parser.add_argument("--linux-command", type=str, default=None)
    parser.add_argument("--starry-command", type=str, default=None)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else find_repo_root()
    if not repo_root:
        print("Error: Cannot find repo root. Use --repo-root.", file=sys.stderr)
        return 2

    contract_path = Path(args.contract) if args.contract else default_contract_path(repo_root, args.syscall)
    try:
        contract = load_contract(contract_path)
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: invalid contract: {exc}", file=sys.stderr)
        return 2

    if contract["syscall"] != args.syscall:
        print("Error: contract syscall does not match --syscall", file=sys.stderr)
        return 2

    run_id = args.run_id or secrets.token_hex(8)
    linux_command = render_command(args.linux_command, run_id) if args.linux_command else None
    starry_command = render_command(args.starry_command or default_starry_command(args.target), run_id)

    if args.linux_raw_log:
        linux_raw_output = Path(args.linux_raw_log).read_text()
        linux_exit_code = args.linux_raw_log_exit_code
    else:
        if not linux_command:
            print("Error: Linux side requires --linux-command or --linux-raw-log", file=sys.stderr)
            return 2
        try:
            linux_exit_code, linux_raw_output = run_command(repo_root, linux_command, run_id, args.timeout)
        except subprocess.TimeoutExpired:
            linux_exit_code, linux_raw_output = -1, f"linux command timed out after {args.timeout}s"
        except FileNotFoundError as exc:
            linux_exit_code, linux_raw_output = -1, str(exc)

    if args.starry_raw_log:
        starry_raw_output = Path(args.starry_raw_log).read_text()
        starry_exit_code = args.starry_raw_log_exit_code
    else:
        try:
            starry_exit_code, starry_raw_output = run_command(repo_root, starry_command, run_id, args.timeout)
        except subprocess.TimeoutExpired:
            starry_exit_code, starry_raw_output = -1, f"starry command timed out after {args.timeout}s"
        except FileNotFoundError as exc:
            starry_exit_code, starry_raw_output = -1, str(exc)

    expected_case_ids = set(contract_case_ids(contract))
    linux_cases, linux_rejected = parse_jsonl_cases(linux_raw_output, run_id, expected_case_ids)
    starry_cases, starry_rejected = parse_jsonl_cases(starry_raw_output, run_id, expected_case_ids)
    report = build_pair_report(
        repo_root=repo_root,
        run_id=run_id,
        target=args.target,
        contract=contract,
        linux_command=linux_command or "<raw-log>",
        starry_command=starry_command if not args.starry_raw_log else "<raw-log>",
        linux_exit_code=linux_exit_code,
        starry_exit_code=starry_exit_code,
        linux_raw_output=linux_raw_output,
        starry_raw_output=starry_raw_output,
        source_path=Path(args.source) if args.source else None,
        binary_path=Path(args.binary) if args.binary else None,
        linux_cases=linux_cases,
        starry_cases=starry_cases,
        linux_rejected_lines=linux_rejected,
        starry_rejected_lines=starry_rejected,
    )
    report_path = write_report(repo_root, report, linux_raw_output, starry_raw_output)

    if args.update_baseline:
        if not report["success"]:
            print("Error: refusing to update baseline from failed verifier report", file=sys.stderr)
            return 1
        update_baseline(repo_root, report)

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_markdown(report, report_path))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
