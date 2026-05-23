#!/usr/bin/env python3
"""Unified starry-evolve state-machine entrypoint."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from contract_schema import ContractError, load_contract, render_contract_markdown
from syscall_audit import run_audit
from verifier import REPORT_SCHEMA_VERSION, git_diff_hash

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def find_repo_root() -> Path | None:
    d = Path.cwd()
    for _ in range(10):
        ct = d / "Cargo.toml"
        if ct.exists() and "[workspace]" in ct.read_text():
            return d
        d = d.parent
    return None


def require_yaml() -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required for status updates")


def choose_target(repo_root: Path) -> dict:
    audit = run_audit(repo_root)
    priority = {"STUB": 0, "PARTIAL": 1, "IMPLEMENTED": 2}
    candidates = sorted(
        [entry for entry in audit["entries"] if entry["status"] in ("STUB", "PARTIAL")],
        key=lambda e: (priority[e["status"]], e["category"], e["sysno"]),
    )
    if not candidates:
        return {"target": None, "reason": "no STUB or PARTIAL syscall candidates"}
    target = candidates[0]
    contract_path = repo_root / "scripts" / "starry-evolve" / "contracts" / f"{target['sysno']}.yaml"
    return {
        "target": target["sysno"],
        "status": target["status"],
        "category": target["category"],
        "handler": target["handler"],
        "handler_file": target.get("handler_file"),
        "handler_line": target.get("handler_line"),
        "contract_exists": contract_path.exists(),
        "next_phase": "contract" if not contract_path.exists() else "patch",
    }


def load_json_file(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"error": f"invalid json: {path}"}


def read_status(repo_root: Path) -> dict:
    status_path = repo_root / "scripts" / "starry-evolve" / "syscall_status.yaml"
    if not status_path.exists():
        return {"syscalls": [], "status_file": str(status_path), "exists": False}
    require_yaml()
    data = yaml.safe_load(status_path.read_text()) or {}
    data["status_file"] = str(status_path)
    data["exists"] = True
    data.setdefault("syscalls", [])
    return data


def latest_report(repo_root: Path) -> dict:
    report_path = repo_root / "scripts" / "starry-evolve" / "reports" / "latest.json"
    report = load_json_file(report_path, {})
    if report:
        report["path"] = str(report_path)
    return report


def framework_status(repo_root: Path) -> dict:
    contracts_dir = repo_root / "scripts" / "starry-evolve" / "contracts"
    contract_files = sorted(contracts_dir.glob("*.yaml"))
    contracts = []
    for path in contract_files:
        try:
            contract = load_contract(path)
            contracts.append(
                {
                    "syscall": contract["syscall"],
                    "status": contract["status"],
                    "cases": len(contract["cases"]),
                    "path": str(path),
                }
            )
        except (ContractError, OSError) as exc:
            contracts.append({"path": str(path), "error": str(exc)})

    status = read_status(repo_root)
    report = latest_report(repo_root)
    baseline = load_json_file(repo_root / "scripts" / "starry-evolve" / "baseline.json", {})
    return {
        "framework": "starry-evolve",
        "mode": "linux-docker-vs-starryos-qemu-pair-verifier",
        "repo_root": str(repo_root),
        "contracts": contracts,
        "status_entries": len(status.get("syscalls", [])),
        "latest_report": {
            "path": report.get("path"),
            "run_id": report.get("run_id"),
            "syscall": report.get("syscall"),
            "target": report.get("target"),
            "success": report.get("success"),
            "case_count": len(report.get("case_results", [])) if report else 0,
        },
        "baseline": {
            "schema_version": baseline.get("schema_version"),
            "source_report": baseline.get("source_report"),
            "case_count": len(baseline.get("cases", [])) if isinstance(baseline, dict) else 0,
        },
    }


def doctor(repo_root: Path) -> dict:
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("repo_root", (repo_root / "Cargo.toml").exists(), str(repo_root))
    add("evolve_entrypoint", (SCRIPT_DIR / "evolve.py").exists(), str(SCRIPT_DIR / "evolve.py"))
    add("verifier", (SCRIPT_DIR / "test_runner.py").exists(), str(SCRIPT_DIR / "test_runner.py"))
    add("pair_demo_script", (SCRIPT_DIR / "run_syncfs_pair.sh").exists(), str(SCRIPT_DIR / "run_syncfs_pair.sh"))
    add("syncfs_contract", (SCRIPT_DIR / "contracts" / "syncfs.yaml").exists(), str(SCRIPT_DIR / "contracts" / "syncfs.yaml"))
    add("syncfs_testcase", (SCRIPT_DIR / "testcases" / "syncfs_pair.c").exists(), str(SCRIPT_DIR / "testcases" / "syncfs_pair.c"))
    add("latest_report", (SCRIPT_DIR / "reports" / "latest.json").exists(), str(SCRIPT_DIR / "reports" / "latest.json"))

    try:
        docker = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True)
        add("docker", docker.returncode == 0, docker.stdout.strip() if docker.returncode == 0 else docker.stderr.strip())
    except FileNotFoundError:
        add("docker", False, "docker command not found")

    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def format_status_markdown(status: dict) -> str:
    latest = status["latest_report"]
    latest_status = "PASS" if latest.get("success") else "MISSING/FAIL"
    lines = [
        "# starry-evolve Status",
        "",
        f"- Mode: `{status['mode']}`",
        f"- Repo: `{status['repo_root']}`",
        f"- Contracts: `{len(status['contracts'])}`",
        f"- Status entries: `{status['status_entries']}`",
        f"- Baseline cases: `{status['baseline']['case_count']}`",
        f"- Latest verifier: **{latest_status}**",
    ]
    if latest.get("path"):
        lines.extend(
            [
                f"- Latest report: `{latest['path']}`",
                f"- Latest run: `{latest.get('syscall')}` on `{latest.get('target')}` (`{latest.get('run_id')}`)",
                f"- Latest cases: `{latest.get('case_count')}`",
            ]
        )
    lines.extend(["", "## Contracts", "", "| Syscall | Status | Cases |", "|---|---:|---:|"])
    for contract in status["contracts"]:
        if "error" in contract:
            lines.append(f"| `{Path(contract['path']).stem}` | ERROR | 0 |")
        else:
            lines.append(f"| `{contract['syscall']}` | {contract['status']} | {contract['cases']} |")
    return "\n".join(lines)


def format_doctor_markdown(result: dict) -> str:
    lines = ["# starry-evolve Doctor", "", f"- Overall: **{'OK' if result['ok'] else 'NEEDS ATTENTION'}**", ""]
    lines.extend(["| Check | Status | Detail |", "|---|---:|---|"])
    for check in result["checks"]:
        lines.append(f"| `{check['name']}` | {'OK' if check['ok'] else 'FAIL'} | `{check['detail']}` |")
    return "\n".join(lines)


def validate_contract(repo_root: Path, syscall: str, render: bool) -> dict:
    path = repo_root / "scripts" / "starry-evolve" / "contracts" / f"{syscall}.yaml"
    contract = load_contract(path)
    if render:
        path.with_suffix(".md").write_text(render_contract_markdown(contract))
    return {
        "syscall": syscall,
        "contract": str(path),
        "status": contract["status"],
        "cases": [case["case_id"] for case in contract["cases"]],
    }


def run_child(repo_root: Path, args: list[str]) -> int:
    return subprocess.run(args, cwd=str(repo_root)).returncode


def load_status(path: Path) -> dict:
    require_yaml()
    if not path.exists():
        return {"syscalls": []}
    data = yaml.safe_load(path.read_text()) or {}
    data.setdefault("syscalls", [])
    return data


def update_status_from_report(repo_root: Path, report: dict) -> None:
    require_yaml()
    status_path = repo_root / "scripts" / "starry-evolve" / "syscall_status.yaml"
    data = load_status(status_path)
    syscall = report["syscall"]
    entries = data.setdefault("syscalls", [])
    entry = next((item for item in entries if item.get("name") == syscall), None)
    if entry is None:
        entry = {"name": syscall}
        entries.append(entry)
    entry["status"] = "VERIFIED" if report["success"] else "TESTED"
    entry["last_report"] = report["run_id"]
    entry["last_target"] = report["target"]
    entry["last_diff_hash"] = report["git_diff_hash"]
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    entry["case_status"] = {
        case["case_id"]: case["status"] for case in report.get("case_results", [])
    }
    status_path.write_text(yaml.safe_dump(data, sort_keys=True))


def append_journal_from_report(repo_root: Path, report: dict, report_path: Path) -> None:
    journal = repo_root / "scripts" / "starry-evolve" / "journal.md"
    status = "VERIFIED" if report["success"] else "FAILED"
    lines = [
        "",
        f"## {datetime.now(timezone.utc).date()} -- {report['syscall']} verifier {status}",
        "",
        f"- Report: `{report_path}`",
        f"- Target: `{report['target']}`",
        f"- Run ID: `{report['run_id']}`",
        f"- Diff hash: `{report['git_diff_hash']}`",
        f"- Linux raw log hash: `{report.get('linux', {}).get('raw_log_hash')}`",
        f"- StarryOS raw log hash: `{report.get('starry', {}).get('raw_log_hash')}`",
        f"- Result: {status}",
    ]
    journal.write_text(journal.read_text() + "\n".join(lines) + "\n")


def record_report(repo_root: Path, report_path: Path) -> dict:
    report = json.loads(report_path.read_text())
    validate_recordable_report(repo_root, report)
    update_status_from_report(repo_root, report)
    append_journal_from_report(repo_root, report, report_path)
    return {
        "recorded": True,
        "syscall": report["syscall"],
        "status": "VERIFIED" if report["success"] else "TESTED",
        "report": str(report_path),
    }


def validate_recordable_report(repo_root: Path, report: dict) -> None:
    required = {
        "schema_version",
        "run_id",
        "syscall",
        "target",
        "success",
        "git_diff_hash",
        "case_results",
    }
    missing = sorted(required - set(report))
    if missing:
        raise RuntimeError(f"verifier report missing keys: {', '.join(missing)}")
    if report["schema_version"] != REPORT_SCHEMA_VERSION:
        raise RuntimeError(f"unsupported verifier report schema_version {report['schema_version']!r}")
    if report["git_diff_hash"] != git_diff_hash(repo_root):
        raise RuntimeError("verifier report git_diff_hash does not match current git diff")


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified starry-evolve workflow entrypoint")
    parser.add_argument("--repo-root", type=str, default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--format", choices=["json", "markdown"], default="json")

    sub.add_parser("select")

    status_cmd = sub.add_parser("status")
    status_cmd.add_argument("--format", choices=["json", "markdown"], default="markdown")

    doctor_cmd = sub.add_parser("doctor")
    doctor_cmd.add_argument("--format", choices=["json", "markdown"], default="markdown")

    contract = sub.add_parser("contract")
    contract.add_argument("--syscall", required=True)
    contract.add_argument("--render-markdown", action="store_true")

    sub.add_parser("test")

    sub.add_parser("verify")

    sub.add_parser("build")

    record = sub.add_parser("record")
    record.add_argument("--report", required=True)

    args, extra_args = parser.parse_known_args()
    if args.cmd in {"test", "verify", "build"}:
        args.args = [*getattr(args, "args", []), *extra_args]
    repo_root = Path(args.repo_root) if args.repo_root else find_repo_root()
    if not repo_root:
        print("Error: Cannot find repo root. Use --repo-root.", file=sys.stderr)
        return 2

    try:
        if args.cmd == "audit":
            audit_result = run_audit(repo_root)
            if args.format == "json":
                print(json.dumps(audit_result, indent=2, sort_keys=True))
            else:
                from syscall_audit import format_markdown

                print(format_markdown(audit_result))
            return 0
        if args.cmd == "select":
            print(json.dumps(choose_target(repo_root), indent=2, sort_keys=True))
            return 0
        if args.cmd == "status":
            result = framework_status(repo_root)
            if args.format == "json":
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(format_status_markdown(result))
            return 0
        if args.cmd == "doctor":
            result = doctor(repo_root)
            if args.format == "json":
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(format_doctor_markdown(result))
            return 0 if result["ok"] else 1
        if args.cmd == "contract":
            print(json.dumps(validate_contract(repo_root, args.syscall, args.render_markdown), indent=2, sort_keys=True))
            return 0
        if args.cmd == "test":
            return run_child(repo_root, [sys.executable, str(SCRIPT_DIR / "test_runner.py"), *args.args])
        if args.cmd == "verify":
            return run_child(repo_root, [sys.executable, str(SCRIPT_DIR / "regression_diff.py"), *args.args])
        if args.cmd == "build":
            return run_child(repo_root, [sys.executable, str(SCRIPT_DIR / "build_checker.py"), *args.args])
        if args.cmd == "record":
            print(json.dumps(record_report(repo_root, Path(args.report)), indent=2, sort_keys=True))
            return 0
    except (ContractError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
