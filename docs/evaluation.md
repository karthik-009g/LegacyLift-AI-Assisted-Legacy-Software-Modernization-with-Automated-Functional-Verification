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

The checked-in report records the hand-built FastAPI baseline at **3/3 scenarios** and **6/6 steps**, with **100% agreement** on each measured response, session, and database field. Those values describe the hand-built implementation and finite synthetic fixtures. Unsupported-behavior classification and human correction effort remain `not_measured`; the separate saved model experiment does not establish them.

The report records the Python minor version and locked package versions so a patch-level Python update does not make the generated artifact differ across Windows and GitHub Actions.

## What the result does not show

The raw drafts have now been attempted in Docker: source-only and hybrid fail import, while runtime-only completes evaluation with 0/6 steps matching. Its session requests return HTTP 500. A separate experiment with labeled startup/observer repairs evaluates all three, each matching 0/6 complete steps. Field scores and diffs appear in [the recorded study](model-experiment.md). Those repairs are not raw model output, and one fixed split cannot establish evidence-condition superiority. Human correction time, model cost, independent unsupported-behavior counts, and repeated-split variance remain unmeasured. The offline report validates and summarizes saved Docker results without executing code.

### Local proposal preflight

Three Groq `openai/gpt-oss-120b` proposals were generated on 2026-11-03. Their prompt hashes remain current. Static review flags authentication, ownership, observer state, and transition concerns. Agent source review and Docker runs on 2026-11-16 confirmed startup failures in the raw drafts; separate compatibility repairs produced measurable behavior, including database failures and contract mismatches. The raw and derived snapshots and reports are preserved under `artifacts/experiments/`; original working files remain ignored under `artifacts/proposals/`.

## Reviewed proposal runner

`legacylift evaluate-proposals` requires exactly one review declaration: `--human-reviewed` for a person's inspection or `--agent-reviewed` for an agent's source review. It reads one proposal per condition, rejects stale or hashless prompts before container launch, and saves results with the actual reviewer type and any repair provenance. A completed run means every candidate was evaluated, not that every candidate passed. Build the image with `docker build --file Dockerfile.evaluation --tag legacylift-evaluation:py311 .`. Use the paths in [the experiment guide](model-experiment.md) to reproduce raw and repaired studies separately.

When Docker is unavailable, `python -m legacylift inspect-proposals` performs a static-only preflight and writes `artifacts/proposals/static_review.json`. It checks proposal schema, condition, current prompt hash, and Python syntax, and flags selected imports/calls plus patterns involving database lifetime, ticket ownership, session authentication and after-state, status transition guards, async middleware, observer arguments, session middleware registration order, and cookie response flow. These are heuristic prompts for manual review, not defect proofs. It never imports or executes candidate code; a successful preflight does not establish functional fidelity or code safety, and does not replace human review or the isolated runner.

The runner disables container networking, uses a read-only root filesystem, drops Linux capabilities, runs as an unprivileged user, and applies CPU, memory, process-count, and timeout limits. It passes no host API key and mounts only the candidate source file. These controls reduce accidental access and side effects but are not a security boundary against deliberately hostile Python. The image includes LegacyLift's Python source, including held-out scenario definitions, so a proposal can inspect the local evaluation code; this is a limitation of the initial prototype. Review candidates before execution and treat results as descriptive. Model-declared unsupported claims are reported but not independently verified; unsupported behavior and human correction effort remain unmeasured.

For machines without Docker, `.github/workflows/generate-groq-proposals.yml` and `.github/workflows/evaluate-reviewed-proposals.yml` provide a manual remote path. It is deferred during local development and can be considered after local project work is complete. Proposal generation requires a fresh `GROQ_API_KEY` repository secret and the Groq account to remain on its Free plan; it sends three requests with no Gemini fallback. The workflow also requires review of all generated proposals and dispatching the evaluation workflow with the generation run ID and review confirmation enabled. The evaluation workflow validates run provenance and uses the same restricted container. Since this repository is public, proposal artifacts are visible to repository readers and should contain only shareable source.

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
