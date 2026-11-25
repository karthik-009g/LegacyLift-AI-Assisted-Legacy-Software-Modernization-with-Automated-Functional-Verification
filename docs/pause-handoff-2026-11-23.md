# Pause handoff — 23 November 2026

The user asked to stop. Start at [RESUME.md](RESUME.md) on resumption. The [session record](session-2026-11-23.md) documents the implementation and earlier checkpoints.

## Verified workflow status

| Workflow | Best relevant outcome | Release state |
| --- | --- | --- |
| Update | Groq `664dedffc38744058e786f61c65d0f25`, 6/6 guidance and 4/4 held out | Approved by goku, exported, replayed 10/10 and verified through the browser |
| Create | Gemini `53ea1530ef2540c7905b8ebc441ada52`, 6/6 guidance and 1/4 held out | Finalized failure. Later Groq 5/6 runs remained at the guidance gate |
| Read | Groq `b10023ae239842bc8ff7dc6c328f7596`, 3/6 guidance | Held-out verification remains gated |

The reproducible update ZIP is `.legacylift/exports/legacylift-update-664dedff-reproducible.zip`, SHA-256 `62897503097adb389240897433817b7528594476f811542f2f938baaafd6c473`. The browser walkthrough is `.legacylift/verification/approved-update-browser-20261123.webm`. The corrected curated mutation campaign detected **9/9**, with the original 8/9 report preserved.

## Interrupted run

Groq create/hybrid `538c48937bf547dbaca14e964f6c26c6` used the compact anchored evidence and the revised repair feedback. `guidance-0.json` records 5/6. `guidance-1.json` records `invalid_repair_edit` because the edit lay outside the supplied windows. The process was stopped while waiting for the free-tier token window for attempt three. Two completed calls and their artifacts remain. No terminal result or held-out replay exists. The exact matching Python launcher and worker were gone after the stop. Docker listed no running LegacyLift-named container. The run log is `.legacylift/verification/create_groq_feedback_fix.log`.

## Verification checkpoint

- Current workspace before the final feedback change had **455 Python tests pass with zero skips** in Docker-enabled testing. The existing Starlette/httpx warning remains. Log `.legacylift/verification/full_docker_anchored_create.log`.
- Earlier fresh snapshot `4ddba0bf9d174099b353de65e793d913` reproduced the locked reference and passed **453 Python tests with zero skips**, plus browser verification.
- The feedback-specific suite passed **140 tests with three Docker opt-in skips** before the last lookup simplification. Saved-data replay and lint covered the final simplification. The full suite on the final source is pending.
- The exact-line audit measured **3/4 Groq** and **4/4 Gemini** create-rule coverage after evidence packing changes. The 11 targets were developer-selected across three workflows. Independent relevance assessment remains open. [Retrieval evaluation](v2-retrieval-evaluation.md).

## Resume order

1. Completed after this pause: reproduced the interrupted trial's rejected edit offline, exposed the missing project lookup in the revised policy, and passed all 456 Docker-enabled tests. See [the latest local checks](RESUME.md). The partial run and its budget accounting are preserved.
2. Measure the updated create policy on a new trial and improve read evidence packing using pinned Redmine source and guidance cases. Give a new trial its own recorded lineage. Finalize only a new candidate that passes all six guidance scenarios. Preserve held-out separation, then request workflow-specific source approval for any new passing export.
3. Finish independent retrieval and broader security evaluation, final source-snapshot reproduction, technical report and demo. The original 27-cell controlled study remains frozen with zero dual passes. Keep new exploratory results under their own run IDs.

Use the existing free-tier Groq and Gemini configuration. OpenRouter setup is deferred at the user's request. Keep all work local and preserve existing artifacts. Docker is needed for independent replay. No user action is needed to retain this checkpoint.
