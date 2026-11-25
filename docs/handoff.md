# LegacyLift Project Handoff

Workbench staged-generation integration is complete across UI/API/worker with immutable saved retries and live request-budget guards. Full Docker suite: **499 passed, zero skips**, 297.61 seconds; lint/format/dependency checks passed. Browser checks: three disposable plus two genuine read-only saved-run checks passed. No hosted calls or new approvals. [RESUME](RESUME.md) tracks remaining migration/release gates.

Additional offline fixes: both staged prompts are checked before the first call; cached-stage provenance must match its actual request ledger before reuse. Related suites: 207 passed, three opt-in skips; lint/format passed. No new model/Docker run or migration result. [Details and continuation](RESUME.md).

Latest short project task: budget-exhaustion termination fixed; actual last verdict and source are preserved without a phantom provider attempt. Related checks: 202 passed, three opt-in skips; lint/format clean. No model API calls or new migration outcome. [Updated resume](RESUME.md).

**Current state, 25 November 2026: paused by the user.** The external AI-assisted review has user acceptance as completed; actual annotations/scoring remain pending and no human-review claim is made. [Acceptance record](../artifacts/v2/independent_retrieval_review_approval_20261125.json). Latest code suite: 481 passed, zero skips. Fresh snapshot reproduced 470 tests/reference/browser before the final tooling changes. Read/create still have no dual-gate release candidates. The requested blind context ZIP remains unbuilt; three clean specification documents are drafted. [Full resume state](RESUME.md). Older active statements below are historical.

**25 November 2026: goal active.** Continue from [RESUME.md](RESUME.md) and [today's record](session-2026-11-25.md). Update has an approved 10/10 export; read/create gates remain open. Current staged read is tracked by `.legacylift/verification/active_read_staged_v2.json`. Preserve its actual outcome before another call. Updating this document does not pause the goal.

> **Current pause, 24 November 2026.** The user stopped because their limits were up. Read [the current pause handoff](pause-handoff-2026-11-24.md) and [RESUME.md](RESUME.md). Read reached 6/6 guidance and 2/4 held out. New composition reuses reviewed update for supporting PUT and is awaiting complete verification. Groq reported the daily token limit. The running full suite was stopped, with its partial log retained. Older checkpoints below are historical.

> **Current pause, 23 November 2026.** The user stopped work. Start with [RESUME.md](RESUME.md), [the pause handoff](pause-handoff-2026-11-23.md), and [the developer record](session-2026-11-23.md). Update is approved/exported and replayed 10/10. Create's earlier 6/6 guidance candidate finalized at 1/4 held out. Read's best is 3/6 guidance. The latest create trial was stopped during its third-request wait. Its first two attempts are saved, and its process is gone. Older entries below preserve historical checkpoints.

> **Current continuation, 22 November 2026.** The user approved the verified update as goku; its checksum-bound local export is complete. Optional larger-request free models are implemented and awaiting key/live validation. Read [RESUME.md](RESUME.md) for current process handles and [free-model options](free-model-providers.md). Older pending-review and no-live-process wording below is historical.

> **Active v2 checkpoint: 22 November 2026.** Start with [RESUME.md](RESUME.md) and [today's implementation record](session-2026-11-22.md). The create scaffold and repair-tool improvements are tested. All four exploratory lineages today are closed failures; source-format recovery is checked offline. The full Docker suite passed 413 tests before the final recovery change. The verified update remains 10/10 and awaits human review. No task process is intentionally left running. Everything below records the original prototype.

> **Historical v1 handoff.** The current project is the Redmine-to-FastAPI v2 modernization study. Use [RESUME.md](RESUME.md), [the accepted v2 roadmap](v2-roadmap.md), and [the latest v2 checkpoint](v2-handoff-2026-11-16.md) for status and next steps. Results below describe the original Flask/FastAPI prototype and must not be presented as v2 migration results.

**Historical v1 update: 2026-11-16.** The initial prototype passed the [requirements audit](completion-audit.md). The original [brief](project-brief.md) was recovered from this chat's earlier complete tool output. Local execution worked with the authorized elevated runner, and Docker Engine 29.9.2 was reachable while Docker Desktop ran. The ordinary sandbox helper still failed during setup.

## Current progress

- Removed the incomplete Windows AppContainer experiment and its mocked/smoke tests. Docker is the sole candidate-execution runtime.
- Added ordered provider-attempt metadata for new proposals and explicit agent-versus-human review provenance. Historical attempt histories remain unknown.
- Automatic generation now uses Groq first and Gemini as backup, matching the user's request. Explicit provider modes still disable fallback. Tests use mocked transports, including primary HTTP 429 followed by successful backup.
- Fixed container diagnostics that hid structured errors behind stderr warnings. Request-level candidate failures are now retained as HTTP 500 responses, with missing session observations recorded explicitly, so comparison can continue.
- Preserved the raw proposals: source-only and hybrid fail import; runtime-only evaluates with 0/6 steps matching and HTTP 500 session responses. Created separately labeled, reproducible compatibility repairs with parent hashes and diffs.
- All repaired conditions completed evaluation, each matching 0/6 full held-out steps. The hand-built baseline still matches 13/13 differential and 6/6 held-out steps.
- The offline demo validates recorded code, prompt, and parent hashes before including experiment results. No new model requests, GitHub jobs, commits, or pushes were made.
- See [model-experiment.md](model-experiment.md) for the exact scores, reproduction commands, and limits. The untracked `ion` file is an unrelated saved terminal-output file and was left untouched.

## Future work and limitations

- No missing file is needed from the user: the original brief is restored as `docs/project-brief.md` and audited in `docs/completion-audit.md`.
- The initial raw trial completed with candidate failures. Two candidates cannot import, so their functional field metrics remain unavailable; operational pass rates are zero. A successful generated reconstruction is not claimed. New trials should preserve these negative results and use fresh keys in the ignored `.env`.
- Human correction effort, repeated trials, latency, and independently classified unsupported behavior are not measured. Do not claim those deliverables are complete.
- Keep GitHub work local until the user authorizes a push after completion.
- The read-only GitHub audit found all 44 recorded runs completed, with zero active. No cancellation or new dispatch was needed.

## Verified on 2026-11-16

- Full suite with `LEGACYLIFT_DOCKER_SMOKE=1` and real process API keys unset: **91 passed**, no skips, one existing Starlette/httpx deprecation warning (11.11 seconds).
- Ruff lint and format checks: passed (60 files formatted).
- `pip check` and `git diff --check`: passed.
- Current Docker evaluation image: built successfully; the trusted-fixture integration passed in the full suite.
- Offline demo: passed, 13/13 differential steps and 6/6 held-out steps, with recorded model results included.
- Deterministic repair generation and rejection of changed candidate/prompt/parent hashes are covered by tests. A pattern scan found zero Gemini/Groq credential patterns in nonignored files; `.env` was not read.
- Raw and repaired model evaluations were run only inside restricted Docker. No API requests or GitHub actions were used.

## Historical snapshot — 2026-11-05

The sections below describe the earlier state and are superseded by the current update above.

## Workspace

- Repository: `C:\Legacy_Lift`
- Work has stayed local. Nothing was committed or pushed, and this work did not start a GitHub Actions run. Existing run status was not verified: the GitHub connector has no cancellation operation, and the Windows UI helper failed during initialization.
- `.env` exists and is Git-ignored. Its contents were not read for this handoff. Proposal JSON files and the static report under `artifacts/proposals/` are also ignored.
- Docker, Podman, nerdctl, and Windows Sandbox are unavailable. The WSL command exists, but no usable WSL distribution is installed. Docker installation was deferred until the user has enough time and storage. No candidate code has been executed outside an isolated runtime.

## Implemented and verified

- The deterministic Flask/SQLite reference, runtime capture, static AST analysis, versioned EER, hand-built FastAPI baseline, differential verification, held-out evaluation, proposal provider boundary, and documentation/demo are present.
- The offline `legacylift demo` passed: 13/13 differential steps, 3/3 held-out scenarios, and 6/6 held-out steps. The report correctly labels the model-condition comparison `not_run`.
- The proposal CLI defaults to direct Groq, so it does not call Gemini unless the user selects `--provider gemini` or `--provider auto`. `auto` opts into Gemini-first with Groq fallback.
- Three Groq GPT-OSS 120B proposals were generated with current prompt hashes. They remain unexecuted and require review.
- Static preflight was extended to flag session/auth/ownership gaps, state-transition guards, observer after-state behavior, and session middleware registration order. The report has schema 1.1 and reports `manual_review_required` where flags are found.
- `README.md`, `docs/evaluation.md`, `docs/architecture.md`, `docs/interview-demo.md`, and `docs/proposal-review.md` describe the current results and limitations.

## Model proposal findings

The current files are `artifacts/proposals/source_only.json`, `runtime_only.json`, `hybrid.json`, and `static_review.json`.

- **source_only:** ticket reads lack session authentication and owner filtering; status updates lack owner scoping and valid-transition checks.
- **runtime_only:** session creation sets a cookie but does not update observer after-state; status updates accept arbitrary transitions.
- **hybrid:** observer middleware may run before session state is available; status updates lack current-state guards, and route database connections are not closed.

These files are drafts, not verified implementations. Do not run them directly on the host. The restricted evaluator requires a working Docker runtime and an explicit human-review declaration.

## Current local verification (2026-11-05)

- `python -m pytest -q`: **71 passed, 1 skipped** (Docker integration test), with one Starlette/httpx deprecation warning.
- `ruff check .`: passed.
- `ruff format --check .`: passed after formatting the new static-review fixture.
- `python -m pip check`: passed.
- `python -m legacylift demo`: passed; differential verification 13/13 steps, held-out baseline 3/3 scenarios and 6/6 steps, model comparison `not_run`.
- `python -m legacylift inspect-proposals`: prompt hashes are current for all three drafts; all require manual review. Candidate code was not executed.
- `git diff --check`: passed; Git printed only LF-to-CRLF notices.

## Remaining work

1. Keep the three raw proposals unchanged for a first comparison; their static preflight is current and their code has been read without execution.
2. When ready after exams, install/enable Docker or provide another isolation runtime that prevents candidate access to host files, secrets, and network.
3. Inspect the exact proposal code in `artifacts/proposals/` and explicitly approve the human-review declaration before evaluation. The current findings and checklist are in `docs/proposal-review.md`.
4. Build the evaluator image:

   ```powershell
   docker build --file Dockerfile.evaluation --tag legacylift-evaluation:py311 .
   ```

5. Run the isolated comparison only after that review:

   ```powershell
   python -m legacylift evaluate-proposals --human-reviewed
   ```

6. Inspect `artifacts/proposals/model_generated_comparison.json`; the three-condition comparison is complete only if each condition is evaluated. Record the actual held-out response, session, and database metrics and discuss limitations. Do not claim that hybrid evidence is better unless measured results support it.
7. Decide how to measure manual correction time for a later corrected-candidate experiment. Keep raw model output separate from corrected code and record edits/time per condition.
8. Update evaluation docs and README with actual results, then rerun the demo and local checks. Push to GitHub only after the user confirms local completion; GitHub runs remain deferred.

## Needed from the user

- Enable Docker or another suitable local isolation runtime when there is enough storage and time. This is required before candidate code can be functionally evaluated.
- Rotate the Gemini and Groq API keys that were pasted into chat before future provider requests; add fresh keys directly to the ignored `.env` file and never paste them into chat. No new model request is needed to evaluate the existing drafts.
- If more model requests become necessary, keep Groq on its Free plan; the repository cannot verify account billing tier.
- Inspect the exact proposals and approve the `--human-reviewed` declaration before the evaluator runs them.
