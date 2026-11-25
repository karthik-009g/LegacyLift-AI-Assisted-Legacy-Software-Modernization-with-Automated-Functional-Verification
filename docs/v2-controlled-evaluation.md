# Controlled evaluation protocol and current evidence

> **23 November checkpoint.** The frozen 27-trial study retains its original outcomes. The later exploratory update was approved and exported, and the exact export replayed at 10/10. The exploratory create run `53ea1530ef2540c7905b8ebc441ada52` matched 6/6 guidance after one repair and 1/4 held out. The curated generated-update mutation rerun detected 9/9 after correcting the closure step in the measurement. The first 8/9 report remains available. [Session evidence](session-2026-11-23.md).

The frozen Redmine-to-FastAPI study `5788dbc46e2a46ef8848d44985a0e583` is **complete at 27/27 recorded trials**: 62/81 reservations, 309,362 reported tokens, and 16 requests with unknown usage. It has **zero guidance passes, zero held-out evaluations and zero dual-gate workflow passes**. Thus data collection is complete, but there is no successful generated migration or evidence that one condition is superior. See the reconciled [summary](../artifacts/v2/studies/5788dbc46e2a46ef8848d44985a0e583/checkpoint-027-reconciled/summary-027.md), [analysis](../artifacts/v2/studies/5788dbc46e2a46ef8848d44985a0e583/analysis-027-reconciled/analysis-027.md), [RESUME.md](RESUME.md) and handoff Section 37.

The study uses fixed code, inputs, provider and request settings. It ran from preserved source snapshot `26029d1806f340398a560bfe0cecb87a`, whose 251-file inventory and 40 study fingerprints were verified. Final complete-state exports live in `checkpoint-027-reconciled/` and `analysis-027-reconciled/`; creation-time and intermediate checkpoint reports remain preserved and historical. See Section 36 of [the handoff](v2-handoff-2026-11-16.md).

After checkpoint 018 the executable study source was preserved as local snapshot 26029d1806f340398a560bfe0cecb87a. All 251 inventory files and 40 study fingerprints verified. All subsequent study calls/audits/exports import that snapshot, including policy 2.3. Development now has policy 2.4, safe quota metadata and opt-in model configuration. These changes are outside this study. The snapshot uses existing controller dependencies. Fresh dependency reproduction remains separate.

Gemini, a new-policy Groq diagnostic and the Qwen preview trial are excluded from study totals. These extra provider requests can compete for organization-level quota and are an availability confound. Their request records and outcomes are preserved. The completed study's service failures and zero passing outcomes do not establish superiority of any evidence condition.

## Frozen inputs and read boundaries

The controller's frozen reference contains 30 predeclared scenarios: six guidance and four held-out cases for each of create, read and update. Reference preparation creates `study/integrity.json` after validating the complete reference checksum, exact scenario identities and requests, and equality of the guidance subset. Existing prepared workspaces can add the seal without changing their original artifacts:

```powershell
python -m legacylift v2 --home .legacylift seal-study
```

This trusted setup operation reads the combined oracle once and returns checksums only. It sends no model request. The seal cannot be overwritten with different expectations; use a new workspace for a changed study.

During guidance replay, the verifier reads the separately sealed guidance file, fixture and private actor mapping. It does **not** open `oracle.json`. It checks the exact guidance bytes and the database/actor buffers handed to the runtime, including changes after preflight. Only final verification opens the combined oracle; generation and repair receive guidance evidence only. The static policy and source/held-out approval checks remain separate gates.

An actual restricted Docker replay, `f23f942766164c2484dc01924d63cfdf`, ran with a controller file-open guard denying `oracle.json`, `held-out.json` and `.env`. It reproduced the saved draft's **1/6 guidance** result with zero model requests. See [the audit](../artifacts/v2/guidance_isolation_audit.json). This establishes a read boundary, not migration success. The subsequent exact-buffer checks also have dedicated tests for changes between preflight and runtime startup.

The seal uses local checksums under the trusted controller's ownership. It detects accidental or inconsistent changes; it is not an external signature or protection against an administrator rewriting the whole workspace.

## Request accounting

Each migration root and all seeded descendants share at most **three actual HTTP request attempts**. A SQLite transaction reserves an attempt before the provider request. Every fallback provider attempt counts separately. A quota error, timeout, or process crash after reservation consumes that allowance conservatively. Local prompt rejection, a missing key and zero-call replay do not consume a request.

```powershell
python -m legacylift v2 --home .legacylift audit-calls RUN_ID
```

Existing call/audit history is imported conservatively. Saved run bindings and root manifests are immutable, and a controlled trial cannot be extended through seeds or reused for a changed diagnostic run. All reservations survive process restarts in ignored `.legacylift/model_calls.sqlite3`; retain that file and the run/study artifacts together.

The cap applies to migration-pipeline calls, not arbitrary calls made outside LegacyLift or an account-wide spending limit. API responses do not establish billing tier. Only the user's configured free-plan accounts are authorized. See the providers' [Groq limits](https://console.groq.com/docs/rate-limits) and [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing).

## Prospective design

```powershell
python -m legacylift v2 --home .legacylift plan-study --provider groq --seed 20261117
python -m legacylift v2 --home .legacylift audit-study STUDY_ID
```

Planning fixes 27 distinct run IDs: three workflows × three evidence conditions × three replicates. It randomizes their order using the recorded seed and fixes one provider/model, zero temperature, at most two repairs, pinned runtime images, the behavior contract, code fingerprints and input/context checksums. Planning reserves the identities, not HTTP requests. The maximum is 81 attempts; fallback providers and seeded extensions are disabled for controlled trials.

The current valid plan is **`5788dbc46e2a46ef8848d44985a0e583`**, created 18 November with seed 20261118, fixed Groq GPT-OSS-120B and medium reasoning. Its prospective [audit](../artifacts/v2/controlled_study_plan_audit_v4.json) and [initial report](../artifacts/v2/controlled_study_initial_report_v4.json) record **27 trials, 81 maximum attempts, zero consumed, zero recorded outcomes at creation**. It fingerprints 40 source/runtime/workbench and asset files and hashes the sealed inputs. Initial reports remain immutable planning evidence, not live counts. The 18 November [checkpoint 012](../artifacts/v2/studies/5788dbc46e2a46ef8848d44985a0e583/summary-012.md) is an interim historical report: 12/27 trials, 28 requests and 147,343 reported tokens. Final counts are in checkpoint 027. Earlier plans and reports remain historical; preserve their original audits. Changed code/inputs require a new plan, never rewriting an existing one.

Shared API requirements declare GET/POST/PUT for read-after-write workflows, POST for create, and PUT for update. The supporting writes are part of the verified read slice. These common method/path requirements are task metadata; held-out payloads and observations are not model inputs. Earlier read trials omitted PUT from the declared surface and remain historical under their original contexts. No new generation has used the corrected scope yet.

Historical first-batch checkpoint: **3/27 cells recorded, eight requests, 43,777 reported tokens, one unknown-usage request, zero guidance/held-out/workflow passes**. [Audited batch 1 report](../artifacts/v2/controlled_study_report_v4_batch1.json). Update/hybrid reached 5/6 guidance; create/source-only failed boot; read/runtime-only stopped after invalid structured repair output. Each is a distinct workflow/replicate, so these are not a matched three-condition comparison. Subsequent batches advanced to the completed checkpoint listed above. Do not infer evidence-condition superiority from exploratory trials, runner simulations or the final study outcomes. Prior model/shared-contract knowledge is a confounder, three replicates are limited, temperature zero does not make hosted generation deterministic, and the selected synthetic private-project scenarios do not cover all Redmine behavior. The common runtime/schema instructions and feedback are supplied across conditions; source-only excludes original runtime examples, not the guidance mismatch feedback needed for bounded repair.

## Execution and resumption

```powershell
python -m legacylift v2 --home .legacylift run-study STUDY_ID --max-trials 1
python -m legacylift v2 --home .legacylift study-report STUDY_ID
```

`run-study` follows the frozen randomized order and defaults to one trial per invocation. It runs guidance first, then independently finalizes only guidance-passing candidates. A provider/runtime failure is recorded and stops that batch. A later explicit invocation advances to the next planned cell; it does not retry the recorded failure. Existing uncertain pipeline requests retain their no-resend guard. A per-study OS lock excludes another runner and releases on process exit, so a leftover lock file is harmless.

The runner saves its in-progress trial before execution and commits a result before advancing. After a controller interruption, a durable result is reused without a new provider call. It validates the planned identity/provider, candidate source, six guidance cases, four held-out cases and report checksums before recording workflow success. Reports recompute rows from their artifacts and ledger, rejecting changed artifacts or rewritten success labels. Failed held-out candidates remain final.

Reports distinguish planned/recorded trials, status/condition counts, guidance/full-workflow passes, reported tokens, unknown token usage and request reservations. An execution state of `completed` means 27 outcomes were recorded; it does not imply a passing migration, favorable condition comparison, security assessment or human source approval. Simulated test runs are not actual model-study evidence.

After a batch finishes, export an audited checkpoint for analysis:

```powershell
python scripts/summarize_controlled_study.py STUDY_ID
```

This calls the same real auditor and refuses to race a live runner. It produces count-versioned report JSON, trial CSV and Markdown under `artifacts/v2/studies/STUDY_ID/`, with pending denominators and unreplayed cases explicit. A different existing checkpoint is not overwritten. These exports summarize recorded evidence; they do not initiate or repair trials.

After a terminal batch, `python scripts/analyze_controlled_study.py STUDY_ID` exports descriptive condition and repair analysis from the audited report and checksum-verified results. It preserves missing replay/usage observations, includes provider/static/boot failures in recorded-trial yield, and excludes pending trials from that denominator. Latency summaries cover parsed provider outputs, excluding failed calls, pacing and runtime execution. Nominal Wilson intervals assume independent binomial trials; these shared-repository repeated trials cannot establish generalization or condition superiority. [Checkpoint 013 analysis](../artifacts/v2/studies/5788dbc46e2a46ef8848d44985a0e583/analysis-013.md) records the first actual export.

## Remaining release evidence

The frozen 27-trial controlled execution and descriptive analysis are complete, but no generated workflow passed guidance or held-out evaluation. First obtain an actual generated workflow that passes both gates, then complete its source review and export. [Measured isolation/advisory assessment](v2-security-assessment.md) exists, with an unpatched development dependency finding and broader security work still open. Same-host source-snapshot reproduction passed; a published-checkout release and final demo/report remain open.
