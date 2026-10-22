# macOS Listening Fixture Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce and fix the two reported listening tests without relaxing production path safety, and make the test environment and error reasons explicit.

**Architecture:** Resolve the trusted system temporary directory when constructing test fixtures; retain the generator's existing rejection of every symbolic link in an asset path. Add structured `BuildError.code` values while preserving Chinese messages. Run Python and Node subprocesses with one selected interpreter, with dependency checks before the test suite.

**Tech Stack:** Python 3.11+, Node.js built-in test runner, Bash, ffmpeg/ffprobe, GitHub Actions.

**Spec:** Parent-approved implementation scope in the task message dated 2026-10-21; the diagnosis and observed evidence will be recorded in `docs/verification/mac-listening-review.md`.

## Global Constraints

- Production `ensure_no_links` retains all existing path checks; do not canonicalize caller-provided asset roots or targets to bypass them.
- Preserve the Chinese diagnostic text, failed generation semantics, and original audio and metadata.
- Add at least `PATH_SYMLINK`, `ASSET_MISSING`, and `ASSET_DIGEST_MISMATCH` codes and record codes in generation failures.
- `PYTHON` override takes priority, then the project's `.venv/bin/python`, then `python3`; use the selection in Node children too.
- Check pytest, Node, ffmpeg, and ffprobe at startup; print versions and suggest missing installations without installing anything.
- Linux symlink simulation is evidence of the reported cause, not native macOS verification. Do not push or deploy.
- Root owns requirements, README, installation and final test reports; leave them untouched.

## Review Focus

- Node and Python construct different temporary fixtures; both need canonical temporary paths.
- Asset root, internal directory, audio leaf, and metadata links must all remain rejected, including internal and dangling links.
- Missing-model status `2` is a preflight path failure, not two recorded item failures.
- A virtualenv executable may itself be a symlink; interpreter selection must preserve the virtualenv entry path.
- CI must test both Linux and macOS and invoke the same local test entrypoint; configuring CI is not evidence it has run.

## Task 1: Listening diagnostics and portable fixtures

**Files:** `scripts/make_listening.py`, `tests_js/listening_assets.test.js`, `tests/test_listening_paths.py`, `docs/verification/mac-listening-red.log`.

**Interfaces:** `BuildError(message: str, *, code: str = 'BUILD_ERROR')`; `.code` is machine-readable while `str(error)` retains the original message. Each failure record gains `code`.

- [x] Capture the unchanged v0.3.3 tests under a symlinked `TMPDIR`; expect 4 pass and the two reported failures.
- [x] Add regressions for stable missing/digest/path codes, symlink refusal, and the Node/Python fixture alias boundary; run and preserve the red result.
- [x] Add error codes and normalize only test temporary directory fixtures.
- [x] Run the focused Python tests and all listening Node tests, including the nested alias regression; expect every test to pass.

## Task 2: One test environment and cross-platform CI

**Files:** `scripts/test_all.sh`, `.github/workflows/tests.yml`.

**Interfaces:** The test entrypoint exports one `PYTHON` executable to all children; dependency failure exits before any tests run.

- [x] Record the existing runner's failure to honor an explicit invalid `PYTHON` using disposable command-boundary probes.
- [x] Implement interpreter precedence and startup checks; print Python/pytest/Node/ffmpeg/ffprobe versions and actionable errors.
- [x] Add an untriggered Linux/macOS CI matrix invoking `bash scripts/test_all.sh` after explicit dependency installation in the CI job.
- [x] Verify invalid override/missing-tool paths and Bash syntax; record environment restrictions. The root agent runs the full entrypoint after parallel changes converge, per the explicit coordination instruction.

## Task 3: Review evidence

**Files:** `docs/verification/mac-listening-review.md` and associated scoped verification logs.

- [x] Record the exact reproduction, cause, code changes, test results, preserved security boundaries, and native macOS limitation.
- [x] Hand the changed files and evidence to the root agent for whole-change independent review and final packaging; do not commit unrelated parallel work.

## Execution record

- Task 1 complete: original alias reproduction 4 pass / 2 fail; new diagnostics 17 failures before the code change; focused final Python 17/17 and Node 7/7, without skips. Logs are under `docs/verification/mac-listening-*.log`.
- Task 2 complete: interpreter precedence and missing dependencies verified through disposable command-boundary probes; Bash syntax and YAML matrix/entrypoint parsing passed. No remote workflow was run.
- Ruling: do not run the full suite while unrelated parallel modules are being changed; the parent explicitly reserves that run until convergence. Cost: this subtask makes no claim about whole-project status.
- Ruling: Node subprocess tests require an execution context permitting local subprocess creation in this container; use the approved escalation rather than skip tests or treat `EPERM` as product behavior. Cost: the evidence is Linux local-process testing, not native macOS or remote CI.
- No shared files outside the assigned scope were committed or deployed. Whole-change independent review and final packaging remain with the root agent.
