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

The checked-in report records the hand-built FastAPI baseline at **3/3 scenarios** and **6/6 steps**. Those values describe only the current implementation and finite synthetic fixtures.

## What the result does not show

No model-generated reconstruction has been run for source-only, runtime-only, or hybrid evidence. The deterministic mock provider does not produce code. Therefore there is no measured condition-level functional fidelity and no evidence that combining evidence improves outcomes. Manual correction time, model cost, and repeated split variance are also unmeasured. A future model experiment must generate a separate app per condition, keep held-out traces out of runtime/hybrid context, and then compare those generated apps against the same held-out set.

## Example mismatch record

When a compared field differs, `artifacts/verification/differential_report.json` uses this shape (values shown here are illustrative):

```json
{
  "field": "response.status",
  "legacy": 404,
  "reconstructed": 200
}
```

The actual checked-in report has zero mismatches. Tests also mutate a captured status in memory to verify that the mismatch reporter identifies the exact field.
