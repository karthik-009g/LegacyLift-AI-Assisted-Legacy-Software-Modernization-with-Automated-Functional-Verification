# Recorded model experiment — 2026-11-16

The Docker evaluator ran the three saved Groq `openai/gpt-oss-120b` drafts. Raw source-only and hybrid fail import; raw runtime-only completes evaluation with 0/6 steps matching. A separate experiment with startup and observer repairs evaluates all three, also with 0/6 complete steps matching for each. The hand-built FastAPI baseline still matches all 13 differential steps and all 6 held-out steps.

These are descriptive results for one synthetic ticket workflow, three held-out scenarios, and one proposal per condition. They do not show that hybrid evidence is superior.

## Raw model output

The original proposals are preserved in [`raw_proposals/`](../artifacts/experiments/raw_proposals/). Their code hashes match the original ignored drafts. No startup or business logic was edited in this group.

| Condition | Recorded outcome | Cause |
|---|---|---|
| Source-only | Execution failed | Imports nonexistent `fastapi.middleware.sessions`. |
| Runtime-only | Evaluated; 0/6 steps match | Uses `Request.scope` instead of the request instance, producing HTTP 500 session responses. |
| Hybrid | Execution failed | Same nonexistent middleware import as source-only. |

The [raw report](../artifacts/experiments/raw_comparison.json) has status `completed_with_candidate_failures`: all three attempts have terminal outcomes, while `functional_evaluation_complete` is false because two cannot import. Their field-agreement rates are unavailable. Raw runtime-only has response agreement 3/24 (12.5%), session agreement 0/12, and database agreement 18/18. Its database stays unchanged because requests fail; that database score does not establish correct behavior.

The report separately computes operational scenario/step pass rates: a candidate that cannot execute earns zero passes over the planned cases, while Docker or runner failures leave rates unavailable and the experiment incomplete. All three raw conditions have zero operational passes. This definition is an exploratory reporting choice added after observing startup failures; it is not a measured field-agreement score or a preregistered analysis.

## Compatibility-repaired experiment

The recipe in `legacylift.evaluation.compatibility` accepts only the three exact saved code hashes. It writes separate proposals with parent hashes, an `agent_compatibility_repair` label, and a [manifest of changes and diffs](../artifacts/experiments/compatibility_repaired/repair_manifest.json). It never imports candidate code.

- Source-only: fix the middleware import and Flask-only `root_path` access; wire the normalized session observer once around every request, including validation failures.
- Runtime-only: inject the actual request and update the observer's session after-state.
- Hybrid: fix the import and register session middleware outside the observer.

These changes make candidates measurable. They do not fix ownership, transitions, validation, response shapes, cookie/header behavior, or SQL defaults. Database constraint failures remain HTTP 500 responses. Missing session observations are explicit `null` values with an error. The comparator continues to the remaining steps.

The [repaired report](../artifacts/experiments/compatibility_comparison.json) records:

| Condition | Scenarios matched | Steps matched | Response fields | Session fields | Database fields |
|---|---:|---:|---:|---:|---:|
| Source-only | 0/3 | 0/6 | 14/24 (58.33%) | 10/12 (83.33%) | 16/18 (88.89%) |
| Runtime-only | 0/3 | 0/6 | 10/24 (41.67%) | 12/12 (100%) | 16/18 (88.89%) |
| Hybrid | 0/3 | 0/6 | 14/24 (58.33%) | 10/12 (83.33%) | 16/18 (88.89%) |

An exact step requires all compared response, session, and database fields to agree. Partial field agreement does not mean a request or workflow is correct.

## Reproduce locally

Use the locked environment from the README, keep Docker Desktop running, and build the evaluator:

```powershell
docker build --file Dockerfile.evaluation --tag legacylift-evaluation:py311 .
python -m legacylift inspect-proposals --proposal-directory artifacts/experiments/raw_proposals
```

After inspecting the exact code, use `--human-reviewed` for a person's review or `--agent-reviewed` for an agent's review. Both modes require source review; the report distinguishes them. The recorded runs were reviewed by Codex and have no human-review declaration.

```powershell
python -m legacylift evaluate-proposals --agent-reviewed --proposal-directory artifacts/experiments/raw_proposals --output artifacts/experiments/raw_comparison.json
python -m legacylift prepare-compatibility-repairs --proposal-directory artifacts/experiments/raw_proposals --output-directory artifacts/experiments/compatibility_repaired
python -m legacylift evaluate-proposals --agent-reviewed --proposal-directory artifacts/experiments/compatibility_repaired --output artifacts/experiments/compatibility_comparison.json
python -m legacylift demo
```

Both recorded experiment commands exit 0 because all attempts have recorded outcomes. Candidate failures remain visible in the raw report. Missing inputs, stale prompts, and Docker or runner failures exit 1. A zero exit code does not mean generated code passed behavioral checks. These commands make no model API requests. The offline demo checks candidate, prompt, and repair-parent hashes before reading results; it never executes model code or contacts Docker.

## Limits and next study

There is one draft per condition and one fixed split. Source-derived contexts contain bounded excerpts and findings from code implementing held-out behavior. The image contains reference and held-out definitions, so this is not an adversarial benchmark. Historical drafts do not contain `provider_attempts`; their missing attempt history is left unknown. New proposals record attempts in order.

Agent repairs are not human correction measurements. Human correction time, independently classified unsupported behavior, model latency, repeated-split variance, and comparative model accuracy remain unmeasured. A broader study should predefine these measurements and collect multiple proposals per condition before claiming evidence-source benefits. No API calls, GitHub dispatches, commits, or pushes were made to obtain these results.
