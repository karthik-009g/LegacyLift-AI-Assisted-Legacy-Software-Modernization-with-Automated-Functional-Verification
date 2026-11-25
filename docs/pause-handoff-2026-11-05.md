# LegacyLift pause handoff — 2026-11-05

This note records the local project state at the user's request to pause work. No GitHub push or workflow was started in this work session. Continue locally when the project resumes.

**Superseded:** See [the current handoff](handoff.md) and [recorded model experiment](model-experiment.md) for the resumed work on 2026-11-16. Docker is reachable, the broken AppContainer experiment was removed, and raw/repaired candidates have now been run in restricted Docker.

## Update — 2026-11-07

The user confirmed Docker Desktop 4.98.0 is installed and the Linux Engine 29.9.2 is responding. This supersedes the earlier note that Docker was deferred. The local shell helper remains unavailable, so Docker-based project checks have not yet been run in this resumed session. The workflow diff has now been reviewed: evaluation accepts Gemini or Groq proposals and downloads the renamed `model-proposals` artifact, while the generation workflow explicitly selects Groq and uploads that artifact name. No workflow was run. Git emitted LF-to-CRLF working-copy warnings for these YAML files.

The user ran the full local test suite on resume: **72 passed, 2 skipped, 1 warning** in 8.84 seconds. Docker integration skipped because it is enabled only in CI; the AppContainer smoke skipped because `LEGACYLIFT_APPCONTAINER_SMOKE=1` was not set. The deprecation warning is from Starlette's use of `httpx` in `fastapi.testclient`. These results verify the default suite only; Docker isolation remains untested locally.

## Update — 2026-11-12

Docker Desktop is now available. User-provided `docker info` output confirms the Linux engine is running (Docker Engine 29.9.2, Docker Desktop 4.98.0). The project evaluation image was successfully built from `Dockerfile.evaluation` as `legacylift-evaluation:py311` using the same command as CI. The trusted-fixture Docker smoke test has not yet run: the local command helper still fails during setup. Next, run it from PowerShell with `$env:LEGACYLIFT_DOCKER_SMOKE='1'; & .\.venv\Scripts\python.exe -m pytest -q tests\test_reviewed_proposals.py -k docker`, then clear the environment variable. This test reads and executes only `tests/fixtures/baseline_candidate.py` in Docker; do not substitute generated drafts.

Correction after smoke test: the user ran that opt-in Docker smoke test successfully on 2026-11-12: **2 passed, 7 deselected, 1 Starlette/httpx deprecation warning** in 3.79 seconds. This is the targeted proposal-test module selection. The full suite with Docker enabled has not yet run. AppContainer smoke remains unverified and is unnecessary when the Docker runtime is available.

On the subsequent resume, an attempted local run of the full suite failed before process creation with `helper_unknown_error: setup refresh had errors`. Retrying `exec_command` with both PowerShell and `cmd.exe`, and resetting/restarting the Node REPL, did not restore local command access. No tests ran in this attempt. The next step is to restore the Codex local command helper or have the user run the full suite with `LEGACYLIFT_DOCKER_SMOKE=1`. The earlier targeted Docker smoke and image build remain verified from user-provided console output.

## Project status

- Milestones 0–5 and 7 are implemented locally. The required model-generated comparison in Milestone 6 remains incomplete, so the project is not complete.
- Docker remains the intended/default execution runtime. The user deferred Docker until after exams and asked for a temporary local workaround.
- The offline demo and proposal-review workflow exist. Model-produced drafts are saved under the ignored `artifacts/proposals/` directory and have **not** been executed.
- The working tree contains uncommitted local changes. Do not reset or clean it blindly; inspect `git status` and the full diff first.
- The user asked that GitHub Actions be stopped and all remaining work stay local until the project is finished. No new GitHub runs were started, but the status/cancellation of any pre-existing remote runs has not been verified.

## Last known checks

Before the latest Windows AppContainer launcher edits, the recorded checks were:

- `pytest`: 71 passed, 1 skipped (Docker-dependent); one Starlette/httpx deprecation warning.
- Ruff lint/format checks and `pip check`: passed.
- Offline demo: 13/13 diff steps, 3/3 held-out scenarios, and 6/6 observed steps.
- A targeted proposal test run recorded 7 passed and 2 skipped before the latest smoke attempt.

These are historical results, not verification of the current worktree. Re-run checks after reconciling the AppContainer edits.

## Most recent work and limitation

An experimental Windows AppContainer runtime was added as an opt-in fallback because Docker was unavailable. It touches `src/legacylift/evaluation/windows_appcontainer.py`, runtime dispatch in `src/legacylift/evaluation/reviewed.py`, CLI runtime selection in `src/legacylift/cli.py`, `.gitignore`, and proposal tests.

The benign smoke test used only the trusted baseline fixture. AppContainer process startup failed in `CreateProcessW` with Windows error 203 before candidate code was launched. The launch implementation was then refactored toward Microsoft's documented single-attribute AppContainer launch pattern, but the final refactor has **not** been inspected or verified. The launcher may be inconsistent or incomplete. Do not run any generated proposal through it until the code is reviewed and an isolated preflight succeeds. Keep Docker as the default. A prior smoke attempt cleaned its temporary profile and workspace staging.

The preflight must establish all of the following before any candidate can run: process token is AppContainer; host marker access is denied; localhost networking is blocked; scratch writes work; runtime inputs are read-only; and child-process creation is blocked. If this cannot be demonstrated reliably, remove/disable the experimental runtime and resume once Docker is available.

## Proposal review findings

The three generated drafts were read as text only; they were not run:

- **Source-only:** ticket reads do not enforce authentication/ownership; status updates lack owner scoping and transition validation.
- **Runtime-only:** session creation does not update observer after-state; status transitions are arbitrary; subject validation/trimming is incomplete.
- **Hybrid:** middleware registration may access the session too early; status transitions are unguarded; database connections are not closed.

All drafts require manual review and correction. Keep `artifacts/proposals/` ignored and do not copy generated code into the application without reviewing the exact draft and completing the sandbox gate.

## Resume checklist

1. Inspect `git status --short` and the complete diff. Reconcile the incomplete AppContainer experiment before relying on the previous check results.
2. Choose the execution path: install/configure Docker after exams, or finish and validate the Windows AppContainer fallback. Do not use an unverified isolation mechanism.
3. Run formatting/lint, targeted tests, then the full local test suite and offline demo. Record fresh outputs.
4. Review the exact generated proposals, fix the security and correctness findings, and only execute them after the isolation preflight passes.
5. Complete the source-only/runtime-only/hybrid comparison and update its report and handoff with measured evidence.
6. Finish remaining project milestones, verify the demo and documentation, and review the final diff. Push or enable GitHub Actions only after the project is complete and the user changes the local-only instruction.

## What is needed from the user

- The user can leave Docker deferred until exams are over. When ready, either provide Docker availability or authorize continued work on the Windows sandbox fallback.
- Gemini and Groq credentials were pasted into this conversation earlier. If they are real, revoke/rotate them before future model calls and replace the values in the project's local `.env`; do not paste keys into chat. `.env` was not read as part of this handoff.
- No other input is needed to resume the local code and documentation work. The project should remain local; no push is pending.

## Resume starting point

Start by reading this handoff, `docs/handoff.md`, and `docs/proposal-review.md`, then inspect Git status/diff and the current AppContainer launcher. Treat all historical test results above as stale until rerun.
