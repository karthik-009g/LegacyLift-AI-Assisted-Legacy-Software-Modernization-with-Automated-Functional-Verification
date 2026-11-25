# Model Proposal Review Checklist

**Update 2026-11-16:** The historical findings below concern the unchanged raw drafts. See [the recorded experiment](model-experiment.md) for the agent-reviewed Docker runs, raw failures, and separately labeled compatibility repairs. Agent review is declared with `--agent-reviewed` and does not claim human inspection.

Review each proposal file independently before enabling evaluation. The review flag is an explicit human declaration, not a safety scanner.

You can run `python -m legacylift inspect-proposals` for a static preflight. It checks syntax and prompt freshness without importing or executing proposal code; it cannot approve a proposal or establish its safety.

The preflight reports `manual_review_required` when selected heuristic patterns need attention. `static_checks_passed` means syntax and prompt freshness passed without those selected flags; it does not establish functional correctness or safety. Manual review is required for every proposal either way.

## Files

- `artifacts/proposals/source_only.json`
- `artifacts/proposals/runtime_only.json`
- `artifacts/proposals/hybrid.json`

Confirm the `condition`, `provider`, `model`, `requires_human_review`, and `prompt_sha256` fields in each file. The evaluator recomputes the current prompt hash and rejects stale drafts before launching a container; regenerate all proposals after changing prompt or evidence inputs. Keep each proposal unchanged after review; the evaluation report records a SHA-256 of the exact code it runs. Review a candidate again if its file changes.

## Behavioral review

- Session identity persists across requests and is represented through the expected cookie behavior.
- Ticket creation matches the legacy validation, response, owner, and database behavior.
- Ticket retrieval enforces the legacy ownership behavior, including its not-found response for another user's ticket.
- Status updates are restricted to the session owner as in the legacy workflow.
- Status updates allow the valid `open` → `in_progress` → `closed` path and reject skipped or invalid transitions as the legacy app does.
- Error responses, selected headers, session transitions, and database deltas match the observed contracts.
- Database connections and fixtures behave correctly across the full multi-request scenario.
- Any inferred behavior or unsupported claim is identified rather than treated as verified.

## Execution-safety review

- Inspect imports, module-level code, file access, process creation, and network calls.
- Check that the candidate does not read `.env`, API credentials, unrelated files, or host data.
- Check that imports and startup code do not perform unintended writes or external actions.
- Do not run candidate code directly on the host. Evaluation is restricted to the isolated Docker workflow described in `docs/evaluation.md`.

Only after reviewing all three files, and confirming their hashes still match, use `--human-reviewed`. Evaluation results remain descriptive for this single synthetic split.

## Current draft review (2026-11-05)

The raw proposals below match the current prompt hashes. Source text was inspected without execution. The static preflight status is `manual_review_required` for all three, and no candidate has been functionally evaluated.

| Condition | Candidate SHA-256 | Findings to resolve or measure |
|---|---|---|
| `source_only` | `e2de6df72fa7a286e25b7a5fe3a4499c1084a9264ae248b3188a0c8d557a53b8` | Ticket retrieval permits unauthenticated reads and does not filter by owner. Status updates check that a ticket exists but not that the current user owns it; they write the requested status without validating a legal transition. |
| `runtime_only` | `37d8c95b9485c2ff7974f95017faaab0e912f15d38a13d11dd394c19d44deed6` | Session creation sets a cookie but the middleware's after-state reads `request.state.user_id`, which the handler never updates. Status updates accept arbitrary transitions. Input trimming and empty-subject behavior also need comparison with the reference. |
| `hybrid` | `d70ddc88251cd76bf64bc9d26bf7629d598ac875fa47a8cba7b4387cea8ba7c2` | Observer middleware registration may access `request.session` before SessionMiddleware initializes it. Status updates do not validate a transition against the stored status. Route handlers open SQLite connections without closing them. |

These are findings about the current raw drafts, not functional test results. Preserve the raw files for a first comparison. If candidates are later corrected, save corrected copies separately and record edits and human time so their results are not presented as raw model output.
