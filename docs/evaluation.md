# Evaluation Protocol and Results

## Split

The checked-in split is explicit in `src/legacylift/evaluation/plan.py`:

| Guidance runtime evidence | Held-out runtime verification |
|---|---|
| `create_ticket` | `hide_other_users_ticket` |
| `retrieve_owned_ticket` | `reject_empty_subject` |
| `valid_status_transitions` | `reject_skipped_status` |

Any scenario added to the fixed suite must be assigned before the evaluation runs; unknown or missing scenarios cause an error. The stored `guidance_trace.json` and `guidance_eer.json` contain only the guidance side of the split.

## Evidence conditions

- **Source-only:** AST findings and bounded excerpts from the complete legacy source; no runtime contracts.
- **Runtime-only:** guidance runtime facts and contracts; no source excerpt.
- **Hybrid:** source findings/excerpts plus guidance runtime evidence.

The evaluation audits each prepared context for held-out runtime scenario IDs. It uses a shared maximum context size and records selected evidence counts, omitted evidence, prompt length, and a prompt hash. This checks context construction and split isolation; it is not a model experiment.

## Metrics

- **Scenario match rate:** held-out scenarios for which every request step matches, divided by all held-out scenarios.
- **Step match rate:** held-out request steps with equal status, selected headers, JSON, cookie attributes, session before/after state, and database before/after state/delta, divided by all held-out steps.
- **Response-contract agreement:** field agreement across status, selected headers, cookie attributes, and JSON.
- **Session-transition agreement:** field agreement for session state before and after each request.
- **Database-state agreement:** field agreement for database snapshots before and after each request and the resulting delta.

The checked-in report records the hand-built FastAPI baseline at **3/3 scenarios** and **6/6 steps**, with **100% agreement** on each measured response, session, and database field. Those values describe only the current implementation and finite synthetic fixtures. Unsupported-claim count and correction effort are explicitly marked `not_measured` because no model-generated reconstruction has been evaluated.

The report records the Python minor version and locked package versions so a patch-level Python update does not make the generated artifact differ across Windows and GitHub Actions.

## What the result does not show

No model-generated reconstruction has been run for source-only, runtime-only, or hybrid evidence. The deterministic mock provider does not produce code, and the Groq provider only saves proposals for review; the separate Docker runner has not yet been used with model output. Therefore there is no measured condition-level functional fidelity and no evidence that combining evidence improves outcomes. Manual correction time, model cost, and repeated split variance are also unmeasured. A future model experiment must review and run a separate reconstruction per condition in a controlled environment, keep held-out traces out of runtime/hybrid context, and compare the resulting apps against the same held-out set. Free-tier limits are account-specific and may constrain the experiment.

## Reviewed proposal runner

`legacylift evaluate-proposals --human-reviewed` reads one proposal per condition from `artifacts/proposals/`, evaluates non-empty proposals, and writes `artifacts/proposals/model_generated_comparison.json`. The flag declares that a person inspected each candidate; it is not an automated code-safety check. Build the evaluation image with `docker build --file Dockerfile.evaluation --tag legacylift-evaluation:py311 .` before running the command.

The runner disables container networking, uses a read-only root filesystem, drops Linux capabilities, runs as an unprivileged user, and applies CPU, memory, process-count, and timeout limits. It passes no host API key and mounts only the candidate source file. These controls reduce accidental access and side effects but are not a security boundary against deliberately hostile Python. The image includes LegacyLift's Python source, including held-out scenario definitions, so a proposal can inspect the local evaluation code; this is a limitation of the initial prototype. Review candidates before execution and treat results as descriptive. Model-declared unsupported claims are reported but not independently verified; unsupported behavior and human correction effort remain unmeasured.

For machines without Docker, `.github/workflows/generate-groq-proposals.yml` and `.github/workflows/evaluate-reviewed-proposals.yml` provide a manual two-run path. The first workflow requires an explicit confirmation that the Groq account is on its free tier, uses the repository secret `GROQ_API_KEY`, and uploads the three proposals. Inspect the artifact before dispatching the second workflow with its run ID and the review confirmation enabled. The second workflow validates run provenance and runs the same restricted container evaluation. Since this repository is public, proposal artifacts are visible to repository readers and should contain only shareable source.

## Example mismatch record

When a compared field differs, `artifacts/verification/differential_report.json` uses this shape (values shown here are illustrative):

```json
{
  "field": "response.status",
  "legacy": 404,
  "reconstructed": 200
}
```

The normal checked-in report has zero mismatches. [`sample_mismatch.json`](../artifacts/verification/sample_mismatch.json) is a separate, clearly labeled example created by changing one captured status to `418` in memory; it is not an observed app failure. Tests verify that the mismatch reporter identifies the exact field.
