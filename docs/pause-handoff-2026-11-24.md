# Pause handoff — 24 November 2026

The user explicitly stopped because their Codex limits were up. Resume only when requested. Start with this file and [RESUME.md](RESUME.md).

## Verified migration outcomes

| Workflow | Current finalized result | Export state |
| --- | --- | --- |
| Update | 6/6 guidance and 4/4 held out, approved by goku | Exported and replayed 10/10 |
| Create | Earlier candidate 6/6 guidance and 1/4 held out | Failed finalization, ineligible |
| Read | `18e1ad28e59546d283aa9e9514bf4a33`, 6/6 guidance and 2/4 held out | Failed finalization, ineligible |

Keep all finalized failed candidates immutable and excluded from repairs/seeding. Their final observations stay outside generation. The original frozen 27-run negative study also remains intact.

## Latest implementation

Read generation now has a composed-controller path, `fastapi-read-v4-reviewed-update`. The controller delegates PUT to the exact reviewed update source from run `664dedffc38744058e786f61c65d0f25`, canonical source hash `d81331cc44c4a2bd59deb29fc6338bbcb03442ec37220f8ef92da722d8a18abc`. The model supplies GET and POST bodies through `read_with_update`. This is a new composed service with explicit supporting-source provenance. It needs its own read verification and approval.

- `runtimes/assets/reviewed_update.py.txt` preserves that exact generated source as packaged data. The loader verifies its hash. `redmine-COPYING.txt` preserves the pinned upstream license.
- `modernization/scaffold.py` wraps the reviewed implementation into an isolated function scope and delegates the PUT endpoint to its original async handler. The existing read scaffold versions remain recognized. Binding metadata includes the supporting run, hash, reviewer and license filename.
- `modernization/generation.py` and `pipeline.py` support two-body generation, retain raw responses, and pass the context-bound Groq reasoning setting. New read trials request medium reasoning with the existing 4,000-token completion cap.
- Read repairs now use reversible compact schema types and prefer one complete model handler. They retain checksum/range guards and fall back for errors outside a handler or an oversized packet.
- Initial instructions were shortened while retaining the date, permission, projection and validation rules. The actual excerpt audit recovered Groq create 3/4 and ordinary read 1/4. The composed read profile measured 2/4. Gemini retained 4/4 for both workflows.

## Quota-paused composed trial

Run `905b974b376d4a7dafd10de59000e527` is `provider_paused`. Its first request returned Groq HTTP 429, dimension `tokens_per_day`, reported limit 200,000. The response supplied a 136-second retry delay at that time. Availability must be checked again on resume. One reservation was consumed, two remain, and no candidate was produced. Metadata is `.legacylift/verification/active_read_composed.json`, with log `.legacylift/verification/read_composed.log` and a saved failure in the run directory.

After resumption, inspect the failure/ledger and current context. If the quota window permits and the context still matches, resume this same lineage with its saved provider policy.

```powershell
Set-Location C:\Legacy_Lift
& .\.venv\Scripts\python.exe -m legacylift v2 --home .legacylift migrate --workflow read --condition hybrid --provider groq --max-repairs 2 --run-id 905b974b376d4a7dafd10de59000e527 --retry-failed-call
```

Gemini's latest separate read root `5f6ada2607b749a2b9217d64da613389` returned HTTP 503 before a draft. GPT-OSS medium project requests in `d1f6b41ffd724987a95e7d33c612e7d2` returned two provider JSON-validation failures. A tiny synthetic medium-reasoning probe succeeded, so unsupported settings were not established. Probe report `.legacylift/verification/groq_medium_structured_probe.json`. Preserve these failures and reservation records.

## Actual verification and remaining checks

- The composed supporting PUT implementation matched **6/6 update guidance scenarios** in restricted Docker. Report `.legacylift/verification/composed_update_guidance.json`. This was a controller integration measurement, with no model request. The receipt predates later comments/license metadata and two-body wiring.
- The latest focused source/provider/repair set passed **164 tests with three Docker opt-in skips** after the composition changes. Lint and format passed.
- The latest completed full suite passed **461 tests with zero skips**, before the reviewed-update composition. Log `.legacylift/verification/full_docker_handler_repair_layout.log`.
- The composed revision's full suite was stopped at the user's request. `.legacylift/verification/full_docker_composed_read.log` contains partial progress with no completed-suite result. Rerun it on resume. No full pass is claimed for that revision.
- Earlier fresh snapshot `37a33de6db3042cca0901e776a34e5e3` completed all seven install stages, matched the reference oracle, passed 457 tests with zero skips and browser checks. It predates the later read interface/composition changes. Reproduce the final code again before release.

All identified pytest processes were stopped. A scoped Docker check found no remaining running LegacyLift containers. No model-generation process was active. Docker Desktop itself was left available. Nothing was committed, pushed, published or deployed.

## Remaining delivery order

1. Complete verification of the composed controller, including packaged assets and licensing, then resume the recorded read lineage if quota permits.
2. Achieve a new read candidate passing guidance and held-out gates. Finish create under the same independent verification contract. Request source approval only for eligible exact-source candidates, then export and replay them.
3. Finish the independent retrieval assessment. [The review packet](v2-retrieval-review-packet.md) links 29 selected workflow/source items with original grades/ranks omitted. Reviewer judgments and a scoring rerun remain pending. Its developer-selected pool remains a limitation.
4. Complete the remaining image-security applicability record, final-source reproduction, browser/demo flow, technical report and interview materials. Python OSV checks found zero known advisories across 48 pinned versions, and the current static policy blocked all seven prohibited specimens in the curated assessment. These measurements retain their stated scope.

Use the existing free-tier Groq/Gemini keys from ignored configuration. The user deferred another provider setup. Preserve all dirty work, source snapshots and original trial evidence. The goal remains incomplete and is paused by request.
