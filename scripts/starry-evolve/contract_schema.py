#!/usr/bin/env python3
"""Machine-readable syscall contract helpers for starry-evolve."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


CONTRACT_SCHEMA_VERSION = 1
REQUIRED_TOP_LEVEL = {
    "schema_version",
    "syscall",
    "status",
    "cases",
}
ALLOWED_STATUSES = {
    "DISCOVERED",
    "ANALYZED",
    "CONTRACTED",
    "IMPLEMENTED",
    "TESTED",
    "VERIFIED",
    "UNSUPPORTED",
}


class ContractError(ValueError):
    """Raised when a syscall contract is missing required machine data."""


def load_contract(path: Path) -> dict[str, Any]:
    text = path.read_text()
    if path.suffix == ".json":
        data = json.loads(text)
    else:
        if yaml is None:
            raise ContractError("PyYAML is required to load YAML contracts")
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ContractError(f"{path} must contain a mapping")
    validate_contract(data, path)
    return data


def validate_contract(data: dict[str, Any], path: Path | None = None) -> None:
    origin = str(path) if path else "contract"
    missing = sorted(REQUIRED_TOP_LEVEL - set(data))
    if missing:
        raise ContractError(f"{origin}: missing keys: {', '.join(missing)}")
    if data["schema_version"] != CONTRACT_SCHEMA_VERSION:
        raise ContractError(f"{origin}: unsupported schema_version {data['schema_version']!r}")
    if not isinstance(data["syscall"], str) or not data["syscall"]:
        raise ContractError(f"{origin}: syscall must be a non-empty string")
    if data["status"] not in ALLOWED_STATUSES:
        raise ContractError(f"{origin}: invalid status {data['status']!r}")

    sources = data.get("linux_sources", [])
    if sources is not None:
        if not isinstance(sources, list):
            raise ContractError(f"{origin}: linux_sources must be a list")
        for idx, source in enumerate(sources):
            if not isinstance(source, dict):
                raise ContractError(f"{origin}: linux_sources[{idx}] must be a mapping")
            if not source.get("type") or not source.get("reference"):
                raise ContractError(f"{origin}: linux_sources[{idx}] requires type and reference")

    matrix = data["cases"]
    if not isinstance(matrix, list) or not matrix:
        raise ContractError(f"{origin}: cases must be a non-empty list")
    seen = set()
    for idx, case in enumerate(matrix):
        if not isinstance(case, dict):
            raise ContractError(f"{origin}: cases[{idx}] must be a mapping")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ContractError(f"{origin}: cases[{idx}] requires case_id")
        if case_id in seen:
            raise ContractError(f"{origin}: duplicate case_id {case_id!r}")
        seen.add(case_id)

        if case.get("unsupported", False):
            if not case.get("reason"):
                raise ContractError(f"{origin}: unsupported case {case_id!r} requires reason")
            continue

        compare = case.get("compare", {})
        if compare is None:
            compare = {}
        if not isinstance(compare, dict):
            raise ContractError(f"{origin}: case {case_id!r} compare must be a mapping")
        if not any(compare.get(key, False) for key in ("ret", "errno", "observable")):
            raise ContractError(f"{origin}: case {case_id!r} must compare at least one field")
        unknown = sorted(set(compare) - {"ret", "errno", "observable"})
        if unknown:
            raise ContractError(f"{origin}: case {case_id!r} compare has unknown keys: {', '.join(unknown)}")


def contract_case_ids(contract: dict[str, Any]) -> list[str]:
    return [
        case["case_id"]
        for case in contract["cases"]
        if not case.get("unsupported", False)
    ]


def render_contract_markdown(contract: dict[str, Any]) -> str:
    lines = [f"# {contract['syscall']} Linux Contract", ""]
    lines.append(f"- Schema: {contract['schema_version']}")
    lines.append(f"- Status: {contract['status']}")
    lines.append("")
    if contract.get("linux_sources"):
        lines.append("## Linux Sources")
        for source in contract["linux_sources"]:
            note = f" - {source['note']}" if source.get("note") else ""
            lines.append(f"- {source['type']}: {source['reference']}{note}")
        lines.append("")
    lines.append("## Pairwise Cases")
    for case in contract["cases"]:
        lines.append(f"- `{case['case_id']}`: {case.get('description', '')}")
        if case.get("unsupported", False):
            lines.append(f"  unsupported: {case['reason']}")
        else:
            compare = case.get("compare", {})
            enabled = [key for key in ("ret", "errno", "observable") if compare.get(key, False)]
            lines.append(f"  compare: {', '.join(enabled)}")
    lines.append("")
    return "\n".join(lines)
