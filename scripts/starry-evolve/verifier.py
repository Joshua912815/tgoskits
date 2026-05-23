#!/usr/bin/env python3
"""Deterministic StarryOS test verification primitives."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ParsedCase:
    case_id: str
    ret: int
    errno: int
    observable: Any
    checksum: str
    raw: dict[str, Any]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_json(data: Any) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical)


def sha256_file(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_diff_hash(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "--binary", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return sha256_text(result.stdout)


def observable_json(observable: Any) -> str:
    return json.dumps(observable, sort_keys=True, separators=(",", ":"))


def fnv1a64(text: str) -> str:
    value = 0xCBF29CE484222325
    for byte in text.encode():
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def case_checksum(run_id: str, case_id: str, ret: int, errno: int, observable: Any) -> str:
    payload = f"{run_id}\n{case_id}\n{int(ret)}\n{int(errno)}\n{observable_json(observable)}"
    return fnv1a64(payload)


def expected_jsonl_record(run_id: str, case_id: str, ret: int, errno: int, observable: Any) -> dict[str, Any]:
    return {
        "type": "starry_evolve_case",
        "run_id": run_id,
        "case_id": case_id,
        "ret": ret,
        "errno": errno,
        "observable": observable,
        "checksum": case_checksum(run_id, case_id, ret, errno, observable),
    }


def parse_jsonl_cases(raw_output: str, run_id: str, expected_case_ids: set[str]) -> tuple[dict[str, ParsedCase], list[str]]:
    accepted: dict[str, ParsedCase] = {}
    rejected: list[str] = []
    unstructured_success: list[str] = []

    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            if "PASS" in stripped.upper() or "PASSED" in stripped.upper():
                unstructured_success.append(f"unstructured success text ignored: {stripped[:120]}")
            continue

        if record.get("type") != "starry_evolve_case":
            continue
        if record.get("run_id") != run_id:
            rejected.append(f"wrong run_id for case {record.get('case_id')!r}")
            continue

        case_id = record.get("case_id")
        if case_id not in expected_case_ids:
            rejected.append(f"unexpected case_id {case_id!r}")
            continue

        try:
            ret = int(record["ret"])
            errno = int(record["errno"])
        except (KeyError, TypeError, ValueError):
            rejected.append(f"invalid numeric result for case {case_id!r}")
            continue

        observable = record.get("observable")
        expected_checksum = case_checksum(run_id, case_id, ret, errno, observable)
        if record.get("checksum") != expected_checksum:
            rejected.append(f"checksum mismatch for case {case_id!r}")
            continue
        if case_id in accepted:
            rejected.append(f"duplicate result for case {case_id!r}")
            continue

        accepted[case_id] = ParsedCase(
            case_id=case_id,
            ret=ret,
            errno=errno,
            observable=observable,
            checksum=record["checksum"],
            raw=record,
        )

    if unstructured_success and not accepted:
        rejected.extend(unstructured_success)

    return accepted, rejected


def case_payload(case: ParsedCase) -> dict[str, Any]:
    return {
        "ret": case.ret,
        "errno": case.errno,
        "observable": case.observable,
    }


def compare_payloads(linux: dict[str, Any], starry: dict[str, Any], compare: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
    fields = {
        field: linux.get(field) == starry.get(field)
        for field in ("ret", "errno", "observable")
        if compare.get(field, False)
    }
    return all(fields.values()), fields


def evaluate_pairwise(
    contract: dict[str, Any],
    linux_cases: dict[str, ParsedCase],
    starry_cases: dict[str, ParsedCase],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in contract["cases"]:
        case_id = case["case_id"]
        if case.get("unsupported", False):
            results.append(
                {
                    "case_id": case_id,
                    "status": "UNSUPPORTED",
                    "reason": case["reason"],
                    "matched": True,
                }
            )
            continue

        linux = linux_cases.get(case_id)
        starry = starry_cases.get(case_id)
        if linux is None or starry is None:
            results.append(
                {
                    "case_id": case_id,
                    "status": "MISSING",
                    "matched": False,
                    "linux": case_payload(linux) if linux else None,
                    "starry": case_payload(starry) if starry else None,
                    "missing": [
                        side
                        for side, value in (("linux", linux), ("starry", starry))
                        if value is None
                    ],
                }
            )
            continue

        linux_payload = case_payload(linux)
        starry_payload = case_payload(starry)
        matched, field_matches = compare_payloads(linux_payload, starry_payload, case.get("compare", {}))
        results.append(
            {
                "case_id": case_id,
                "status": "PASS" if matched else "FAIL",
                "matched": matched,
                "compare": case.get("compare", {}),
                "field_matches": field_matches,
                "linux": linux_payload,
                "starry": starry_payload,
                "linux_checksum": linux.checksum,
                "starry_checksum": starry.checksum,
            }
        )
    return results


def build_pair_report(
    *,
    repo_root: Path,
    run_id: str,
    target: str,
    contract: dict[str, Any],
    linux_command: str,
    starry_command: str,
    linux_exit_code: int,
    starry_exit_code: int,
    linux_raw_output: str,
    starry_raw_output: str,
    source_path: Path | None,
    binary_path: Path | None,
    linux_cases: dict[str, ParsedCase],
    starry_cases: dict[str, ParsedCase],
    linux_rejected_lines: list[str],
    starry_rejected_lines: list[str],
) -> dict[str, Any]:
    case_results = evaluate_pairwise(contract, linux_cases, starry_cases)
    success = (
        linux_exit_code == 0
        and starry_exit_code == 0
        and not linux_rejected_lines
        and not starry_rejected_lines
        and all(case.get("matched", False) for case in case_results)
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "mode": "linux_starry_pair",
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "syscall": contract["syscall"],
        "target": target,
        "success": success,
        "contract_hash": sha256_json(contract),
        "git_diff_hash": git_diff_hash(repo_root),
        "source_hash": sha256_file(source_path),
        "binary_hash": sha256_file(binary_path),
        "linux": {
            "command": linux_command,
            "exit_code": linux_exit_code,
            "raw_log_hash": sha256_text(linux_raw_output),
            "rejected_lines": linux_rejected_lines,
        },
        "starry": {
            "command": starry_command,
            "exit_code": starry_exit_code,
            "raw_log_hash": sha256_text(starry_raw_output),
            "rejected_lines": starry_rejected_lines,
        },
        "case_results": case_results,
    }


def build_report(**kwargs: Any) -> dict[str, Any]:
    """Backward-compatible alias for callers that already build pair reports."""
    return build_pair_report(**kwargs)


def report_filename(report: dict[str, Any]) -> str:
    return f"{report['timestamp'][:10]}_{report['syscall']}_{report['target']}_{report['run_id']}.json"
