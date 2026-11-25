# LegacyLift v2 model-trial log

## Current pause — 24 November 2026

| Root | Result |
| --- | --- |
| `5f6ada2607b749a2b9217d64da613389` | Compact-contract Gemini read returned 503, no draft. |
| `d1f6b41ffd724987a95e7d33c612e7d2` | Medium-reasoning Groq read returned two provider JSON-validation failures, no draft. One reservation remains. |
| `905b974b376d4a7dafd10de59000e527` | Composed read received a daily-token-limit 429, no draft. Provider-paused with two reservations remaining. |

A separate tiny synthetic structured-output probe succeeded with medium reasoning. It sent no project source or final observations. `.legacylift/verification/groq_medium_structured_probe.json` records its 747 reported tokens. It does not establish that the full project response fits the same output budget.

## 24 November 2026 — resumed create and anchored read

| Later root | Actual result |
| --- | --- |
| `8d13e601e44f4215a0e69506a00f7876` | Read v3, 2/6, out-of-window block, indentation block. Exhausted. |
| `6fc8065b362d43bb9733d790992a77d7` | Compact-schema whole-handler repairs, 2/6 → 1/6 → 4/6. Exhausted. |
| `18e1ad28e59546d283aa9e9514bf4a33` | Read with source-backed date/journal rules, 6/6 on its first request. Exact-source finalization matched 2/4 held out. Finalized and ineligible for repair/seeding/export. |
| `bbab2f4ec79148dda00b05c3897bf93a` | Create with date rules, 3/6 → static block → 1/6. Exhausted. |
| `7e0d61f805dd460682e0442208341e7f` | Fixed Qwen comparison, static block → static block → 3/6 guidance. Exhausted. |

The finalized read source has checksum `2c0a69e739f613029ee3e9f68926d6c952cc6d2d28e43698d8c376633b385815`. No further generation is permitted for that candidate. Its final diagnostics are not guidance. A separate fixed Qwen comparison uses the current public source and guidance, with metadata at `.legacylift/verification/active_read_qwen.json`.

Create v3 `dcb0a48d53a94dcdaa4f45d6e5e7b030` measured 4/6 guidance on its initial and final drafts, with one intervening out-of-window repair rejection. Outsider and unknown-project requests received 401 instead of the observed validation responses. The downstream permission branch was omitted from the earlier source view. V4 adds that branch alongside the lookup. The separate v4 root `e9449d3acef249b2a91c13220d520f3b` measured 1/6, an out-of-window static block, then 1/6. Both roots are exhausted. No held-out run was authorized by these results.

Groq create `ca444f8fa45a4440a430665fac83ee77` passed 5/6 guidance, failing only the anonymous response content-type value. Two repair responses contained empty edit lists and were rejected before execution. The three-request root is exhausted. Its repair view omitted the failing 401 response. The follow-up v3 policy includes that line in an offline saved replay at 12,545 bytes. New trial metadata is `.legacylift/verification/active_create_visibility_v3.json`.

Gemini read `bc4251a112a24611b97af3466a441b7e` used anchored read source spans. The provider returned 503 twice, including one explicit retry. No generated source or guidance score exists. Two of its three reservations were consumed. Exact-line prompt coverage improved to 4/4 selected read rules on Gemini and 1/4 on Groq. These spans were developer-selected. Independent relevance review remains open.

## 23 November 2026 — focused windows, exact evidence and repair feedback

| Groq create/hybrid run | Recorded attempts | State |
| --- | --- | --- |
| `9f6b432bc8744386afafcabf3ac6fd38` | 2/6 guidance, 1/6 guidance, syntax block | Exhausted, no held-out replay |
| `e911e5d9aea54a999b0536fd1fd4c8fb` | 5/6 on all three drafts. A repair fixed the outsider write and regressed unknown-project validation. The last draft returned six errors with three distinct values. | Exhausted, no held-out replay |
| `538c48937bf547dbaca14e964f6c26c6` | 5/6 guidance, then `invalid_repair_edit` for an edit outside the supplied windows | Stopped by request while waiting for the third request. Two completed calls, no terminal result or held-out replay |

The last trial used the revised total/distinct error counts and current-case preservation feedback. The saved work includes the draft, guidance checks, and each proposed source view. Start diagnosis with the exact rejected patch and its source view. [Pause handoff](pause-handoff-2026-11-23.md).

## Read adapter v2 and create source policy

Read adapter `fastapi-read-v2` passes nested issue fields to the write handlers and offers a UTC serializer for SQLite timestamps. The generated fragment retains authorization, validation and persistence decisions. Groq run `e4999010219a4b69b372e218439c5254` submitted three invalid Python fragments. Full regeneration after each parser finding did not recover. An offline replay of prompt construction showed that the new parser-window policy can send all three exact error locations within the existing request limit. This preflight made zero requests and changed no draft. A provider trial of the parser-window policy remains due.

Create uses public Redmine `Issue.safe_attributes=`, `allowed_target_trackers`, presence and length validators, controller setup and default display settings. New context and repair prompts carry these rules. Gemini `071579810cc542c8bdeba9e5863ae53c` returned 503. Initial Groq `6c96a9da2b01441788a21787535fb5df` matched 5/6. Its first repair failed syntax review, and its final repair failed static review with two undefined priority variables after rollback. Updated Groq `31ef8738d1284f5ea6c94452d8138670` matched 1/6 and returned two repair proposals exceeding the 100-line replacement limit, including the retry with the limit stated. Both Groq roots used three requests. The previous finalized trial's held-out observations remain sealed. [Resume notes](RESUME.md).

The later parser-window Groq read `97d4842378cc4f449c13a1aa7908aae4` used three requests and failed static review each time for integration issues and redefinition of supplied helpers. The model code did not execute. Grouped repair feedback now retains every name from the eight reported helper redefinitions in a 13,046-byte offline prompt. A separate synthetic, zero-project-data provider probe returned HTTP 400 `json_validate_failed` when asked for three items under an array limit of two. This did not establish usable constrained-decoding support for oversized repair proposals. The local validator remains the acceptance boundary. [Groq Structured Outputs](https://console.groq.com/docs/structured-outputs).

## 23 November 2026 — exact-source create finalization and read scaffold

Create/hybrid `53ea1530ef2540c7905b8ebc441ada52` used two Gemini 3.5 Flash-Lite requests. Its guidance score improved from 2/6 to 6/6 after one numbered repair. Separate Docker finalization matched 1/4 held out. That exact source is ineligible for review/export and its terminal held-out evidence stays outside subsequent generation and repair.

Standalone read/hybrid `d3dbb857e53b455898f66caa9cf4914e` received HTTP 503 from Gemini. Standalone Groq `f0719e782d374fa3a7aac70a7f8f8917` matched 0/6 on all three drafts, exhausting its cap. The initial draft queried nonexistent `users.api_key`. The next protocol uses a checksum-bound scaffold for the three route adapters, bound token lookup, SQLAlchemy mapping/transaction helpers and fixture clock. The model owns visibility, authorization decisions, writes and HTTP semantics. The first Gemini call with that scaffold also returned HTTP 503 (`e2254ccc8def4b04bf4ab34aac70bdb7`). Original run results are preserved.

Scaffolded Groq `ff54dff809464398b6bd14b0e4edae92` used three requests. Two drafts failed to start due to an invalid FastAPI import. The last attempted to register duplicate routes and was blocked in static review. The checked follow-up `9a51ce2dac9e4b5c85d0db4719485b86` also exhausted three requests with three static blocks. Its last draft still registered duplicate routes despite the new checks.

Protocol `read-scaffold-bodies-v2` gives the model three separate body arrays and one optional helper array. The controller adds function declarations to the fragment and retains the exact provider response in `response-N.json`, with its hash recorded in provenance. Numbered repair still sees assembled model code inside checksum-bound windows. Both 12-case offline prompt audits passed. The hybrid request retained six guidance cases at 13,853 UTF-8 bytes and three source excerpts for Groq, and 25,135 bytes and 18 excerpts for Gemini. Groq trial `b10023ae239842bc8ff7dc6c328f7596` had one undefined helper in the initial static review. The first and second repairs both ran in Docker and matched **3/6 guidance**. The final repair removed an exception from SQLite timestamp conversion. It still used login as author name, emitted SQLite timestamp strings in JSON, and rejected the valid supporting create call. The three-request budget is exhausted. No held-out verification ran.

## 22 November 2026 — synchronous create and read line-array trials

See [the implementation and trial record](session-2026-11-22.md). Three create lineages consumed three requests each and remain closed: `6e6e2061905c4e33b9c378c7f38b6ba4` (0/6, 0/6, static block), `createv4named20261122` (3/6, static block, 3/6), and `createv4contract20261122` (3/6, static block, static block). Read run `readlines20261122` consumed three requests and ended with three syntax-review blocks because lines included filename/number labels; nothing executed. No held-out replay or approval. Later repair/template/recovery changes were checked against saved failures without changing those artifacts. All four roots are exhausted. The earlier update dual pass and original negative controlled study are unchanged.

## 21 November 2026 — permission reader trial

Create/hybrid run 5cf1452dd9cb4e9e9389b80ec7141ca3 tested the v3 scaffold's explicit project permission reader. The model used that helper. Groq reported 1,962, 304, and 369 completion tokens. Independent guidance matched 1/6 on all three attempts. The initial synchronous engine was opened with async with. Later attempts fixed individual calls but retained direct Engine.execute elsewhere. The lineage is closed at three requests. No held-out evaluation or approval exists.

## 21 November 2026 — separated implementation request

Trial acab42fc331949be9bc0de21d96441fe used separate system instructions and evidence messages and the implementation_lines response field. The first completion was an executable route. Completion tokens were 1,909, 233 and 971 over its three requests. Guidance was 1/6 on the initial and first repaired sources. The last source failed static review. No held-out evaluation occurred.

The zero-provider replay in .legacylift/verification/create-scaffold-v2-preflight-acab42fc combined the unchanged initial model fragment and the new v2 scaffold. The replay progressed beyond the prior helper error to a SQL error in the fragment's role query. It remained 1/6. Its app, component hashes and guidance report are saved separately.

## 21 November 2026 — scoped create assembly

- b271aeeef42740bdb3563098864d5815 used the controller scaffold with the original line-array format. It returned a copied evidence fragment that failed to boot, an out-of-window repair that was rejected, and then an executable replacement route with 1/6 guidance. Completion token counts were 2,562, 1,473, and 2,192. The final route requested the wrong authentication header for the declared API contract.
- b6f4504503784aa59d601cf61bc68124 used clearer route instructions and the evidence-object rejection pattern. It returned quoted evidence rather than a route, then 0/6 guidance with the first repair. The last repair failed Python review. Completion token counts were 792, 1,413, and 1,282. The new preflight also recognizes quoted-only fragments.

Both lineages are exhausted. No held-out data was used and no create equivalence is established. The existing frozen experiment outcomes remain separate.

## 21 November 2026 — create response and repair windows

- ff847bb6a030469bb5338a8100ca6a35, create/hybrid/auto. Groq returned a line-array draft using 6,282 tokens. The draft passed static review and 3/6 guidance cases. It split role permissions on commas and rejected the valid creator. The next repair response contained zero edits, which failed validation. Gemini fallback returned HTTP 503. The saved repair view omitted the parser. The improved view exposes the parser, write and rendering code within the 14,000-byte cap. Three request slots consumed.
- 36e327db060b4b5c8f419c31e3f4c667, create/hybrid/auto with the updated prompt and window selector. Groq returned HTTP 400 after its completion cap truncated the structured response. Gemini returned HTTP 503. Two request slots consumed. Further attempts need reduced generation work per response.

Neither run reached held-out verification. Both trials are exploratory and separate from the frozen study.

## 21 November 2026 — first update workflow with both verification passes

Run 664dedffc38744058e786f61c65d0f25 used one Groq GPT-OSS 120B request for update/hybrid, low reasoning, temperature zero and a 4,000-token completion cap. Groq reported 3,762 prompt, 2,404 completion, and 6,166 total tokens. The complete returned file used the line-array format and passed static review. Independent Docker replay matched **6/6 guidance and 4/4 held-out scenarios**. It was the first draft and received no repair. Human review and export are pending. See [the review packet](v2-update-candidate-review.md).

Preceding exploratory run b21a7edbf6434a54a81941ff4ca3a67d used three Groq requests. Its two runnable attempts matched 1/6 then 2/6 guidance. In both, plain SQLAlchemy rows were accessed as name-keyed mappings, causing HTTP 500s. Its third attempt proposed a repair whose old text did not match the requested line. The compiler rejected it and preserved the previous file. The next implementation accepts numbered replacements only inside visible, checksum-bound source windows. A zero-request preflight confirmed that it could apply the disputed edit to the actual saved file without changing the archived draft. Trial 9480d0b0e2f84ec19912a78ee4f7bb39 produced no draft. Medium reasoning exhausted Groq's 4,000-token completion budget, and Gemini returned 503.

These trials are exploratory. The frozen 27-cell study below still records zero guidance passes and no held-out evaluations. Statements below about the absence of a dual pass describe earlier checkpoints.

**Updated 20 November 2026.** This log records selected free-tier attempts from the local Redmine-to-FastAPI study. Generation and repair use public source and synthetic guidance. No generated workflow passes both gates. The frozen study is complete with zero guidance, held-out, or full-workflow passes. Current continuation details are in [RESUME.md](RESUME.md) and handoff Section 38.

The frozen study `5788dbc46e2a46ef8848d44985a0e583` is **27/27 outcomes, 62/81 requests, 309,362 reported tokens, and 16 unknown-usage requests**. It produced zero guidance passes, zero held-out evaluations, and zero full-workflow passes. Use the [checkpoint-027 summary](../artifacts/v2/studies/5788dbc46e2a46ef8848d44985a0e583/checkpoint-027-reconciled/summary-027.md) and [descriptive analysis](../artifacts/v2/studies/5788dbc46e2a46ef8848d44985a0e583/analysis-027-reconciled/analysis-027.md); checkpoint 025 is historical. No recorded cell should be repeated.

Qwen lineage `ed983864b1ba4392b000531939f059ab` was resumed only to send its locally rejected repair after source/context checks passed. It returned HTTP 400 `json_validate_failed`, leaving two of three requests consumed and one unused. Do not retry before understanding the structured-response failure. The initial request was not resent.

Separate exploratory run `4227e72b7a4e434bab86ef857b6faebf` used three Groq `openai/gpt-oss-120b` calls. Attempt 0 and attempt 1 were blocked by static review; the first repair edit also failed exact old-text validation. The final source passed static review but failed independent guidance at **0/6**. Guidance mismatches covered issue `lock_version`, journal/version/timestamp effects, and empty response bodies/cache-control on forbidden, unauthorized, and not-found requests. The run has no held-out evaluation, human approval, or security certification. It is separate from the fixed study.

New separate Qwen update/hybrid root 45458a739be445d58d8fb232219a3884 initially returned HTTP 400 in thinking mode. Its explicit preserved-file instruct-mode retry generated two candidates at **3/6 → 3/6**. Three total requests are consumed and the root is closed. Instruct settings are effort none, temperature 0.7, hidden reasoning and 16,384 output cap. New shared request-body contract root 5e77dff1bee14758803c1bb93e4b0f3b scored **3/6** then returned repair HTTP 429. Safe metadata names tokens per minute with limit 8,000. It consumed two requests. Both are exploratory model/mode changes outside the fixed study. No held-out results or manual candidate changes fed these trials.

Guidance and source inspection show the latter candidate guesses `update_issues` and denies valid updates with 403. Pinned public Redmine declares `edit_issues` for that action in lib/redmine.rb line 108. Source-grounded permission/action extraction is the next retrieval improvement. Earlier asynchronous Request-body misuse was addressed by a shared framework instruction, and twelve current prompt variants passed the local byte audit. These changes require new trial context provenance.

## Current trials

| Run | Workflow | Model | Generation/repair outcome | Independent result |
|---|---|---|---|---|
| `6d72faa157a2473693f823f3cd51735e` | Create | Gemini 3.8 Flash | Returned a whitespace-only source file. The prior AST policy incorrectly accepted it; the isolated candidate failed to boot. | No scenarios ran; no held-out evaluation. Empty-source validation and ASGI-app checks were added. |
| `afb664160b864dc9b258e70894c18ac0` | Create | Gemini 3.8 Flash, low thinking | Produced a candidate; static review initially rejected its function-local fixture-clock alias. The reviewer was corrected to resolve aliases within lexical scope. | This draft was then used as the seed for the next guidance-only trial. No held-out data was read. |
| `75ee041be40a4784ac7aaeeeab36f928` | Create | Gemini 3.8 Flash, one bounded repair | Seeded attempt scored 1/6 guidance; one model repair then scored 6/6 guidance. | Separate held-out evaluation scored 2/4. The run remains incompatible. Its held-out report is final for this run and must not be used to repair or seed another run. |
| `d3bc93ee8dfa4685bf5f35cf7c81fb63` | Read | Gemini 3.8 Flash, low thinking | Request timed out before a draft was returned. | No candidate or held-out evaluation. The uncertain request was not resent automatically. |
| `33c649fbbc424bad93bb3f28b6ab9fef` | Read | Groq `openai/gpt-oss-120b` | Draft returned, but static review rejected invalid Python syntax at line 107. Candidate code was not executed. | No guidance or held-out scenarios ran. |
| `88b2e867b4734973a622f7341f4c4c4e` | Read | Groq `openai/gpt-oss-120b`, one bounded repair | The seeded draft remained statically blocked; the repair call paused after a 429 response with a 1,739-second retry delay. | No repaired candidate, Docker execution, or held-out evaluation. |
| `8a0b809d115c42abba91723831beae85` | Read | Gemini 3.8 Flash, one bounded repair | Seeded from the saved syntax-blocked read draft; the single repair request timed out before returning a draft. | No repaired candidate or held-out evaluation. |
| `961f51b36ba64418b1414dfdecd2a6c4` | Read/hybrid | Groq `openai/gpt-oss-120b` | New source-packing context; one initial generation and one repair, 7,550 + 4,334 tokens. Both stopped at the old static HTTPException-body rule, which did not recognize the repaired custom handler. | Original outcome remains `static_review_blocked`; no held-out evaluation. |
| `c844d6c4eb1e4724a8d02a656aa7cb1c` | Read/hybrid | Saved Groq repair, no new model request | Provenance-linked replay of the exact preceding repair after static policy 2.1 recognized a handler registered on the candidate's `app`. | **3/6 guidance passed**; incompatible. No held-out evaluation. |
| `d4cf77f85abd43c693f836999af22e5d` | Read/hybrid | Groq `openai/gpt-oss-120b`, one further repair from the replayed draft | Repair was first rejected locally at the prompt cap with no request sent. Adaptive reference/feedback compaction rebuilt the unsent prompt at 15,402 bytes; the single completion used 4,178 tokens. | **3/6 → 2/6 guidance** after removing permission checks. Independent replay rejected the regression. No held-out evaluation. |
| `0b245176c1c644f2b7596f879c91fd2f` | Read/hybrid | Gemini 3.8 Flash | Fresh trial using source packing and observed body-emptiness evidence; HTTP 503 `provider_unavailable` before a draft. | No candidate execution or held-out evaluation; not retried. |
| `9da28f863ecc41b9b7a5138322266cb4` | Read/hybrid | Groq `openai/gpt-oss-120b` | Fresh permission-normalization contract. Initial host AST rejected a same-quote f-string; a restricted Python 3.14.10 parse later proved the original syntax valid. One model repair changed quoting, then stopped at default HTTPException-body findings. 7,460 + 3,701 tokens. | Original `static_review_blocked` outcome preserved; no application scenarios or held-out evaluation. |
| `1b8fb06bf1ba46c587878410b0282d4f` | Read/hybrid | Groq `openai/gpt-oss-120b`, final repair in the preceding chain | Model removed exception detail text, which does not remove FastAPI's default JSON response body. 4,046 tokens. | Still statically blocked; no candidate execution or held-out evaluation. This chain is closed at three calls / 15,207 reported tokens. |
| `4fac00e1b9304944b1b811e920ace180` | Read/hybrid | Saved Groq repair, zero new requests | Exact source replay under policy 2.3, where default HTTP-body findings are compatibility advisories. | **2/6 guidance**; timestamp TypeError, missing-header 422, supporting create-state differences. No held-out evaluation. Earlier recorded outcomes stay intact. |
| `2a0611ffcc034ad68586ca467cc0c7a9` | Read/hybrid | Groq `openai/gpt-oss-120b` | Fresh date/header contract. Initial and repaired drafts passed 0/6 then 1/6 guidance; the final request returned 429 with a 1,633-second retry delay. | Three HTTP attempts consumed the lineage cap. Two completions; no held-out evaluation. Preserve the quota failure without retry. |
| `2e78c842302f4c38bf694236baf3dbe5` | Read/hybrid | Gemini 3.8 Flash | Fresh backup trial with the new context, rather than a resend of the older failed request. Initial request ended in ReadTimeout before a draft. | One uncertain HTTP attempt remains consumed in the ledger. No candidate, retry or held-out evaluation. |
| `f23f942766164c2484dc01924d63cfdf` | Read/hybrid | Saved Groq repair, zero new requests | Exact preceding Groq draft replay with a frozen-study seal and controller guard rejecting combined-oracle, held-out-report and credential reads. | **1/6 guidance**, matching the saved draft. No held-out evaluation. This validates read isolation, not compatibility. |
| `9c2fa730698d48a1bcd84d984efbfded` | Create/hybrid | Groq `openai/gpt-oss-120b` | Fresh trial after the earlier advertised wait elapsed. Draft hardcodes a local SQLite filename; authenticated requests fail to open the supplied database. Its first repair request returned 429 with a 1,376-second retry delay. | **1/6 guidance**. Two HTTP attempts consumed, one remaining; no retry, held-out evaluation or approval. |
| `4977c50fd1ed4e32836e19a32b2d71dd` | Create/hybrid | Gemini 3.8 Flash | Fresh create-only backup after a metadata GET returned HTTP 200. Generation ended in ReadTimeout before a candidate. | One uncertain request consumed, two slots remaining. No retry, candidate execution or held-out evaluation. Session completed before the user paused. |
| `9c2fa730698d48a1bcd84d984efbfded` — explicit follow-up, 18 Nov | Create/hybrid | Groq GPT-OSS 120B | Original state was preserved in a checksummed checkpoint. One deliberate retry of its known 429 consumed the last slot; the repair changed connection arguments but retained the wrong literal URL. | **1/6 → 1/6**; three total requests now consumed, zero remaining. Further repair blocked locally. No timeout request was resent or held-out evaluation performed. |
| `4883a543bb544052b2568b12bffb4a2d` | Create/hybrid | Groq GPT-OSS 120B | Fresh trial with the shared database environment contract. The candidate reads the supplied URL; subsequent failures are validation/response mismatches. Three completions, **16,157 reported tokens**. | **0/6 → 0/6 → 1/6**; closed at three actual requests. The basic request is wrongly required to provide status_id. No held-out evaluation or approval. |

## Guardrails and current interpretation

- A guidance pass is not a complete migration pass. The create candidate failed held-out verification, and no workflow candidate has passed both gates.
- The held-out report is stored separately and its values are not included here. The pipeline now records only a summary in `result.json` and refuses to seed any run with a `held-out.json` artifact, even if a result summary is stale.
- The create draft that failed held-out verification is not eligible for repair. Future generation must rely on public source and guidance evidence only.
- Static review is a capability filter, not a security certification. No candidate has been human-approved or exported.
- Earlier Groq quota-paused trials remain preserved and were not resent. The new source-packing chain used three actual calls: one generation and two repairs, totaling 16,062 reported tokens. Its zero-call replay and local prompt rejection are not additional requests. The chain is closed at its repair bound; no more repairs should be appended to it.
- The newest date/header trial made three Groq HTTP attempts, including a final quota error, and the fresh Gemini backup made one timed-out attempt. These four attempts are recorded by the new persistent ledger; only two returned completions. No request was resent and no held-out evaluation occurred in this checkpoint.
- The later Groq create trial adds two HTTP attempts: one completion and one quota rejection. Its database URL defect comes from guidance diagnostics and saved source, not held-out feedback. The planned controlled study remains separate at zero requests. No older failed request was resent.
- Final pause accounting: the four newer read/create trial roots together consumed **seven generation HTTP attempts with three completions**. Zero-call replays and the model metadata GET are separate. All requests finished or timed out before the pause; no retry or new held-out evaluation occurred. Preserve failed/uncertain attempts when resuming.
- Repair feedback now preserves the union of already passing guidance case IDs, retains them across static-review rejection, and rejects held-out results. Repair instructions explicitly forbid bypassing membership/role checks to fix status mismatches. These changes followed the rejected permission-removal repair; they were not applied retroactively to its recorded outcome.
- Google currently lists Gemini 3.8 Flash as free of charge on its Free tier; the API response does not reveal whether a configured account is on the Free or a paid tier. Do not make further remote calls unless they remain within the user's free-tier-only constraint.

All run source, prompts, provider metadata, guidance reports, and the separate held-out report remain under the ignored `.legacylift/runs/` directory. No keys or raw held-out differences belong in this log.

18 November diagnostics are separate from migration trials: one Groq probe returned structured output (292 tokens), one Gemini probe returned 503. Neither sent repository/fixture data nor executed returned code. Together with the explicit known-quota retry and three fresh create requests, six HTTP reservations were made today. No actual controlled-study cell ran. See `artifacts/v2/provider_diagnostics_20261118.json` and handoff Section 26. Earlier no-retry statements describe their checkpoints; the later explicit known-quota retry is documented and preserved, while timed-out calls remain unresent.

Provider eligibility reference: [Groq's official limits](https://console.groq.com/docs/rate-limits) lists `openai/gpt-oss-120b` under Free Plan limits (30 RPM, 8K TPM, 200K TPD), with organization-specific exceptions. The client does not upgrade the account or claim that response headers prove billing status.

## Later 18 November checkpoint

Exploratory create/hybrid/Groq **`ed2bbe8070bb451890ae59ab39b54cfe`** consumed three requests / 15,405 reported tokens and closed at static_review_blocked. The initial low-reasoning draft scored 0/6 guidance due to synchronous-engine async use and other response mismatches. Both repairs failed exact edit validation (overlap, then nonmatching source); neither was applied or replayed. No held-out evaluation. Budget zero; do not extend or seed this run.

After that run, added complete-source fallback following an invalid edit, an explicit synchronous SQLAlchemy contract and medium Groq reasoning with recorded provenance. This changes the protocol; earlier exploratory outcomes are not controlled measurements of it. Groq documents the supported effort parameter in its [official reasoning guide](https://console.groq.com/docs/reasoning); its actual benefit remains unmeasured.

New frozen plan **`5788dbc46e2a46ef8848d44985a0e583`**, seed 20261118, fixes 27 cells, at most 81 requests, Groq GPT-OSS-120B/medium and 40 code/asset fingerprints. Its first three-cell batch is executing. The zero-call prospective audit and initial report v4 remain planning evidence; actual outcomes must be recorded separately after the runner finishes. No generated dual-gate success is claimed. These additions bring today's pre-study migration/diagnostic reservations to nine; study requests are additional and audited separately.

Latest actual controlled checkpoint: **8/27 cells, 21 requests, 117,320 reported tokens, three requests with unknown usage, no guidance/held-out/workflow pass**. All three batches finished. Best final guidance is 5/6 in update/hybrid; other outcomes include boot/static failures, invalid output/JSON generation, and one final repair HTTP 413. Recorded cells were not retried. See [checkpoint 008](../artifacts/v2/studies/5788dbc46e2a46ef8848d44985a0e583/summary-008.md); no condition superiority follows from this incomplete, stratified sample.

Separate fresh exploratory Gemini update/hybrid `e709c21a946646f49c57bcba32042811` returned 503 on its initial request, no draft; one reservation / two unused, no retry. It is excluded from the fixed-Groq study. At that earlier checkpoint, scoped reservations totaled 31 across nine pre-study attempts, 21 controlled requests and this Gemini request; later Qwen roots are outside that count. Unknown usage is not zero. All intentionally started provider jobs are terminal. The goal is now paused at the user's request; older in-flight statements are historical.

## Requested pause — 18 November 2026

Checkpoint **012** is audited/exported: **12/27 controlled cells, 28 requests, 147,343 reported tokens, six requests without token usage, zero guidance passes, held-out evaluations or workflow passes**. Later batches added provider JSON failures, source-only update 1/6, initial read/hybrid HTTP 413 and create/runtime-only repair HTTP 413 / Retry-After 2. No recorded cell was resent. All six started batches are terminal, no in-progress trial or owned application container remains. Next untouched run: `cdaa096814ab44638fa9867898d4f1c7`. The goal is paused at the user’s request; no new model request until resumed. Keep the frozen protocol and review request-size/quota feasibility before continuing. Today's model-provider reservations total 38, including earlier exploratory/diagnostic calls; unknown usage is not zero. See RESUME and handoff Section 32.

## Update effects-contract trial — 20 November 2026

The prior update/hybrid run `d4ecf292b50049e6980596a387202725` used three Groq GPT-OSS-120B calls. Its observed sequence was 2/6 → 3/6 → 0/6 guidance. The middle attempt denied otherwise valid edits by inventing additional `edit_own_issues` and `add_issue_notes` permissions beyond the route's `edit_issues` binding; the final attempt regressed status and response-header behavior. There was no held-out evaluation. This trial motivated the update-only effects/permission contract in `generation.py` and the update schema allowlist.

Fresh run `b028997414d24696bb2bf3d08a955bb0` used the revised update/hybrid prompt with automatic provider fallback. Groq rejected the call with HTTP 413 `request_too_large` (8,356 requested tokens versus an 8,000 TPM limit); Gemini returned HTTP 503. Two reservations were recorded, the run ended `provider_failed`, and no candidate was produced or evaluated. It must not be retried unchanged. The local prompt audit passed all 12 variants under the 16,000-byte cap, but bytes are not model tokens. The update/hybrid prompt was 15,495 bytes, with 2,417 serialized source bytes and six guidance examples; source packing expanded into the schema space saved by the update-specific table filter. The follow-up allocator fix and run are recorded below.

## Update/hybrid 14 KB prompt trial — 20 November 2026

The revised allocator caps update/hybrid source evidence at 2,581 serialized bytes and the initial/repair prompt at 14,000 bytes. The local audit passed all 12 variants with zero provider calls and no held-out reads. Update/hybrid was 13,588/14,000 bytes, with six source documents, 1,851 serialized source bytes and all 6/6 guidance examples. The largest variant measured 15,966/16,000 bytes.

Run `34b4b664ca43403b8eb85a2169229b4a` then tried update/hybrid with the existing free-tier provider policy. Two earlier network requests failed with `ConnectError`; the last request completed with Groq `openai/gpt-oss-120b`, medium reasoning and temperature zero. Usage was 3,748 prompt + 3,574 completion = 7,322 tokens; latency about 8.6 seconds; prompt SHA-256 `e800a643de6621db7213d457bbc55a3a1077ddf89f49fdf678222d2e9d2d99b3`.

The response was saved to `.legacylift/runs/34b4b664ca43403b8eb85a2169229b4a/draft-0.py` (5,695 bytes) and blocked at line 1 by static review as `invalid_python`. It was **not executed**. No guidance or held-out case ran, and there is no approval or security certification. The lineage's three request slots were consumed and its terminal state is `provider_failed`. Do not retry it or manually repair/execute the draft. Inspect it as text only; before any new repair lineage, validate existing seed eligibility and source/context hashes and locally measure the exact repair prompt. Full Docker-enabled suite passed 382 tests with zero skips after these implementation changes; tests do not prove migration quality. Frozen-study outcomes remain unchanged.
