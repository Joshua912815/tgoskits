# Prompt: Write detailed documentation for starry-evolve

You are writing project-facing documentation for `scripts/starry-evolve`, an AI-assisted continuous kernel improvement framework for StarryOS.

Write the documentation in Chinese. Keep the tone neutral, engineering-focused, and suitable for a repository README or design document. Do not mention a specific AI vendor unless quoting an existing file path such as `.claude/skills`.

## Source Context

The framework lives under:

- `scripts/starry-evolve/`
- `.claude/skills/starry-*`
- `.agents/skills/starry-*`
- `.claude/settings.json`
- `AGENTS.md`

The current implementation is intentionally lightweight. Its core idea is:

> AI proposes contracts, patches, tests, and explanations; deterministic tools decide whether the change is verified.

The central runnable path is a Linux Docker vs StarryOS QEMU pair verifier:

1. A contract YAML file under `scripts/starry-evolve/contracts/<syscall>.yaml` defines case ids and which fields to compare.
2. A small C test emits structured JSONL records with `run_id`, `case_id`, `ret`, `errno`, `observable`, and `checksum`.
3. The same test binary is run once on Linux inside Docker and once inside StarryOS QEMU.
4. `scripts/starry-evolve/test_runner.py` compares StarryOS output against Linux output case by case.
5. Only the verifier writes reports under `scripts/starry-evolve/reports/`.
6. `scripts/starry-evolve/evolve.py record --report <report>` derives `syscall_status.yaml` and `journal.md` from the verifier report.

## Important Commands

Document these commands:

```sh
python3 scripts/starry-evolve/evolve.py doctor
python3 scripts/starry-evolve/evolve.py status
python3 scripts/starry-evolve/evolve.py select
python3 scripts/starry-evolve/evolve.py contract --syscall syncfs --render-markdown
scripts/starry-evolve/run_syncfs_pair.sh x86_64
python3 scripts/starry-evolve/evolve.py record --report scripts/starry-evolve/reports/latest.json
python3 scripts/starry-evolve/tests/test_verifier.py
```

Explain that `run_syncfs_pair.sh x86_64` is the current end-to-end showcase path. It prepares the test binary, injects it into the StarryOS rootfs, runs Linux oracle execution through Docker/QEMU user mode, runs StarryOS through QEMU system mode, and produces `reports/latest.json`.

## Files To Explain

Cover these files and their responsibilities:

- `evolve.py`: unified entrypoint and workflow state machine.
- `test_runner.py`: pair runner and verifier report writer.
- `verifier.py`: JSONL parsing, checksum validation, report construction, diff/source/binary hashing.
- `contract_schema.py`: YAML contract validation and Markdown rendering.
- `regression_diff.py`: syscall/target/case-level regression comparison.
- `syscall_audit.py`: syscall implementation audit with handler file/line evidence.
- `prepare_pair_test.sh`: compiles and injects the syncfs pair test into rootfs.
- `run_syncfs_pair.sh`: one-command E2E syncfs demonstration.
- `testcases/syncfs_pair.c`: minimal structured JSONL syscall testcase.
- `contracts/syncfs.yaml`: current machine-readable example contract.
- `hooks/pre_commit_check.py`: stop/pre-commit guard against unverified kernel changes.
- `.claude/skills/starry-*` and `.agents/skills/starry-*`: AI workflow prompts and agent responsibilities.
- `.claude/settings.json`: least-permission command allowlist.

## Required Sections

Write the final documentation with these sections:

1. Overview
2. What Problem This Solves
3. Architecture
4. Trust Boundary: What AI Can and Cannot Decide
5. Contract Format
6. Linux Docker vs StarryOS QEMU Pair Verification
7. End-to-End Demo: `syncfs`
8. Skill and Agent Workflow
9. Hooks and Permission Model
10. Reports, Baseline, Journal, and Status Files
11. How To Add The Next Syscall
12. Testing The Framework Itself
13. Current Limitations
14. Roadmap

## Accuracy Requirements

- Do not claim every syscall is contracted. Only `sync` and `syncfs` are examples at this stage.
- Do not claim all architectures are supported by the pair demo. The current runnable showcase is `x86_64/syncfs`.
- Do not say terminal text like `PASSED` is trusted. It is rejected unless accompanied by valid structured JSONL with the correct `run_id` and checksum.
- Explain that the Linux run is the oracle for comparable fields.
- Explain that `reports/` artifacts are generated outputs and are ignored by git except for `.gitignore`.
- Mention that `pytest` is optional for the current tests because `scripts/starry-evolve/tests/test_verifier.py` can run directly with Python unittest.

## Style Requirements

- Be concrete and file-path-oriented.
- Include command snippets.
- Include one Mermaid diagram for the workflow.
- Include one example YAML contract snippet.
- Include one example JSONL testcase output line, but keep it short.
- Avoid marketing language. The goal is to show a credible, runnable framework.
