import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contract_schema import ContractError, validate_contract
from regression_diff import compare_cases
from verifier import build_pair_report, expected_jsonl_record, parse_jsonl_cases


def sample_contract():
    return {
        "schema_version": 1,
        "syscall": "sync",
        "status": "CONTRACTED",
        "linux_sources": [{"type": "man-pages", "reference": "sync(2)"}],
        "cases": [
            {
                "case_id": "sync_returns_zero",
                "compare": {"ret": True, "errno": True, "observable": True},
            }
        ],
    }


class VerifierTests(unittest.TestCase):
    def test_contract_schema_accepts_valid_contract(self):
        validate_contract(sample_contract())

    def test_contract_schema_rejects_missing_compare_fields(self):
        contract = sample_contract()
        contract["cases"][0]["compare"] = {"ret": False}
        with self.assertRaises(ContractError):
            validate_contract(contract)

    def test_contract_schema_rejects_unknown_compare_key(self):
        contract = sample_contract()
        contract["cases"][0]["compare"] = {"ret": True, "signal": True}
        with self.assertRaises(ContractError):
            validate_contract(contract)

    def test_verifier_accepts_run_id_and_checksum_record(self):
        run_id = "run123"
        record = expected_jsonl_record(
            run_id,
            "sync_returns_zero",
            0,
            0,
            {"result": "no_error"},
        )
        accepted, rejected = parse_jsonl_cases(
            json.dumps(record),
            run_id,
            {"sync_returns_zero"},
        )
        self.assertFalse(rejected)
        self.assertEqual(accepted["sync_returns_zero"].errno, 0)

    def test_verifier_rejects_reward_hacking_passed_text(self):
        accepted, rejected = parse_jsonl_cases("PASSED\nall tests PASS\n", "run123", {"case"})
        self.assertEqual(accepted, {})
        self.assertTrue(rejected)
        self.assertIn("unstructured success text ignored", rejected[0])

    def test_verifier_rejects_bad_checksum(self):
        run_id = "run123"
        record = expected_jsonl_record(run_id, "case", 0, 0, {})
        record["checksum"] = "forged"
        accepted, rejected = parse_jsonl_cases(json.dumps(record), run_id, {"case"})
        self.assertEqual(accepted, {})
        self.assertEqual(rejected, ["checksum mismatch for case 'case'"])

    def test_verifier_report_contains_contract_hash(self):
        contract = sample_contract()
        run_id = "run123"
        record = expected_jsonl_record(
            run_id,
            "sync_returns_zero",
            0,
            0,
            {"result": "no_error"},
        )
        accepted, rejected = parse_jsonl_cases(json.dumps(record), run_id, {"sync_returns_zero"})
        report = build_pair_report(
            repo_root=ROOT.parents[1],
            run_id=run_id,
            target="host",
            contract=contract,
            linux_command="true",
            starry_command="true",
            linux_exit_code=0,
            starry_exit_code=0,
            linux_raw_output=json.dumps(record),
            starry_raw_output=json.dumps(record),
            source_path=None,
            binary_path=None,
            linux_cases=accepted,
            starry_cases=accepted,
            linux_rejected_lines=rejected,
            starry_rejected_lines=rejected,
        )
        self.assertTrue(report["success"])
        self.assertIn("contract_hash", report)

    def test_pair_report_requires_both_sides(self):
        contract = sample_contract()
        run_id = "run123"
        record = expected_jsonl_record(
            run_id="run123",
            case_id="sync_returns_zero",
            ret=0,
            errno=0,
            observable={"result": "no_error"},
        )
        linux_cases, rejected = parse_jsonl_cases(json.dumps(record), run_id, {"sync_returns_zero"})
        report = build_pair_report(
            repo_root=ROOT.parents[1],
            run_id=run_id,
            target="riscv64",
            contract=contract,
            linux_command="true",
            starry_command="true",
            linux_exit_code=0,
            starry_exit_code=0,
            linux_raw_output=json.dumps(record),
            starry_raw_output="",
            source_path=None,
            binary_path=None,
            linux_cases=linux_cases,
            starry_cases={},
            linux_rejected_lines=rejected,
            starry_rejected_lines=[],
        )
        self.assertFalse(report["success"])
        self.assertEqual(report["case_results"][0]["status"], "MISSING")

    def test_pair_report_detects_errno_mismatch(self):
        contract = sample_contract()
        run_id = "run123"
        linux_record = expected_jsonl_record(
            run_id,
            "sync_returns_zero",
            0,
            0,
            {"result": "no_error"},
        )
        starry_record = expected_jsonl_record(
            run_id,
            "sync_returns_zero",
            0,
            22,
            {"result": "no_error"},
        )
        linux_cases, linux_rejected = parse_jsonl_cases(json.dumps(linux_record), run_id, {"sync_returns_zero"})
        starry_cases, starry_rejected = parse_jsonl_cases(json.dumps(starry_record), run_id, {"sync_returns_zero"})
        report = build_pair_report(
            repo_root=ROOT.parents[1],
            run_id=run_id,
            target="riscv64",
            contract=contract,
            linux_command="true",
            starry_command="true",
            linux_exit_code=0,
            starry_exit_code=0,
            linux_raw_output=json.dumps(linux_record),
            starry_raw_output=json.dumps(starry_record),
            source_path=None,
            binary_path=None,
            linux_cases=linux_cases,
            starry_cases=starry_cases,
            linux_rejected_lines=linux_rejected,
            starry_rejected_lines=starry_rejected,
        )
        self.assertFalse(report["success"])
        self.assertFalse(report["case_results"][0]["field_matches"]["errno"])

    def test_case_level_regression_only_for_same_case_failure(self):
        baseline = {
            "source_report": "base",
            "cases": [
                {
                    "syscall": "sync",
                    "target": "riscv64",
                    "case_id": "sync_returns_zero",
                    "status": "PASS",
                    "matched": True,
                }
            ],
        }
        current = {
            "run_id": "current",
            "syscall": "sync",
            "target": "riscv64",
            "case_results": [
                {
                    "case_id": "sync_returns_zero",
                    "status": "FAIL",
                    "matched": False,
                }
            ],
        }
        comparison = compare_cases(baseline, current)
        self.assertEqual(comparison["regressions"][0]["case_id"], "sync_returns_zero")


if __name__ == "__main__":
    unittest.main()
