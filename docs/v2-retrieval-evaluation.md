# Ruby source retrieval development diagnostic

## 24 November 2026 — anchored read evidence

Later explicit creation-date and optional-journal instructions consumed more of the fixed small prompt budget. The subsequent measured coverage is Groq **2/4 create and 0/4 read**, and Gemini **4/4 for both**. Report `.legacylift/verification/retrieved_lines_read_defaults_v1.json`. The earlier measurements below retain their own prompt versions. Instruction compression remains open to recover literal evidence coverage.

New read/hybrid contexts reserve exact pinned spans for issue lookup, author display, timestamps and journal fields. The current audit measures **4/4 on Gemini** and **1/4 on Groq**, compared with the previous 1/4 and 0/4. Groq's 690-byte source allocation retains the lookup but cannot accommodate all four span records. Report `.legacylift/verification/retrieved_lines_read_anchored_v1.json`. Both profiles retain their prompt limits. Focused source/prompt/repair checks passed 96 tests after the subsequent create repair change. The first anchored Gemini trial returned 503 twice, so no behavioral improvement has yet been measured.

## Exact source lines in the sent prompt

`scripts/audit_retrieved_lines.py` checks eleven developer-selected spans from the pinned public source. It verifies the source tree and matches the actual outbound excerpt text to those source lines. It tolerates Tree-sitter removing indentation from the first line of a method. Complete retention requires every line of the target span to be present. This measures evidence delivery for the declared checks. Independent human relevance judgments remain open.

```powershell
& .\.venv\Scripts\python.exe scripts/audit_retrieved_lines.py --output .legacylift/verification/retrieved-lines-repeat.json
```

Create hybrid now uses the same reversible database typing and header dictionaries as read. This frees room for four explicitly selected public-source excerpts within the existing cap. The Groq packet carried all six guidance cases at 13,799 UTF-8 bytes, including the issue's default-priority call, the default lookup and API association fields. The tracker fallback span still does not fit in full. Gemini retains all four create spans. The encoding round-trip tests check that guidance requests, responses, schema and route declarations survive the compaction.

| Profile | Workflow | Complete spans before | Complete spans after |
| --- | --- | --- | --- |
| Groq | Create | 0/4 | 3/4 |
| Gemini | Create | 0/4 | 4/4 |
| Groq | Read | 0/4 | 0/4 |
| Gemini | Read | 1/4 | 1/4 |
| Groq | Update | 0/3 | 0/3 |
| Gemini | Update | 3/3 | 3/3 |

Reports are saved as `.legacylift/verification/retrieved_lines_v1.json` and `retrieved_lines_v2.json`. The create packing change was guided by the measured misses. These counts describe the selected source facts and do not measure independent relevance, application behavior or generation success.

This diagnostic measures source retrieval for the three selected Redmine 4.2.10 workflows. It uses public source and workflow requirements, makes no model requests, executes no application, and does not read study observations or model-run artifacts.

The 29 graded labels in [retrieval_judgments.json](../artifacts/v2/retrieval_judgments.json) cover read (8), create (9), and update (12). They identify entrypoints, API serialization, authentication/authorization, parameter assignment, transitions, and journal persistence. Grades are essential (3), relevant (2), or supporting (1). These are developer judgments authored after the existing ranking and anchors. This is a three-query development diagnostic; an independent relevance test set and human annotation agreement remain open.

Run from the repository root:

```powershell
& .\.venv\Scripts\python.exe -m legacylift v2 --home .legacylift evaluate-retrieval
```

The command verifies the imported source tree against its provenance, analyzes it afresh, and saves [retrieval_report.json](../artifacts/v2/retrieval_report.json). It preserves cached evidence and frozen studies. The report includes source-tree, index, retriever and judgment checksums, parse limitations, ranked evidence IDs, missing labels, and retained source-budget coverage. Ranking is deterministic; the report contains no raw source or private fixture values.

Three strategies share the parser, corpus, query strings and 32-document limit:

- `bm25`: lexical retrieval alone.
- `workflow`: the existing production default, combining workflow anchors, BM25, and a penalty for unrelated controllers.
- `dependency`: an experimental variant adding bounded expansion from anchored facts along unambiguous static call-name and Rails API-template relationships. Expansion uses at most two hops, with maximum bonuses of 24 and 12; repeated callers do not accumulate bonuses. These relationships remain inferences, with support evidence IDs retained. They are not runtime call traces.

## Measured results, 17 November 2026

Recall uses the declared positive labels as its denominator. Unjudged documents count as grade zero. nDCG uses gains of `2^grade - 1` and logarithmic position discounting. The JSON includes precision, reciprocal rank and recall/nDCG at 8, 16 and 32.

| Strategy | Workflow | Labeled recall @8 | Labeled recall @32 | nDCG @8 |
|---|---|---:|---:|---:|
| BM25 | Create | 0.111 | 0.444 | 0.127 |
| Workflow | Create | 0.667 | 0.778 | 0.672 |
| Dependency | Create | 0.556 | 0.889 | 0.658 |
| BM25 | Read | 0.250 | 0.375 | 0.377 |
| Workflow | Read | 0.875 | 0.875 | 0.978 |
| Dependency | Read | 0.875 | 1.000 | 0.960 |
| BM25 | Update | 0.250 | 0.417 | 0.510 |
| Workflow | Update | 0.500 | 0.750 | 0.782 |
| Dependency | Update | 0.583 | 0.833 | 0.870 |

Dependency expansion improves development recall at 32 for each workflow, but reduces early create relevance. It remains an experimental diagnostic strategy; production ranking is unchanged.

## Source packing and actual prompt audit

The original 1,800-character hybrid source budget retained two long prefixes: only 1/9 labeled create documents, 2/8 read documents, and 2/12 update documents. That measured report is preserved as [retrieval_report_prefix_v1.json](../artifacts/v2/retrieval_report_prefix_v1.json).

The `diverse-line-windows-1` source packer now spreads coverage across workflow entrypoints, identity/permissions, serialization, assignment, transitions and audit logic. It preserves the existing workflow ranking, supplements eligible static dependency facts and shared controller helpers, and selects one contiguous run of complete source lines per document. A small request omits an overlong line rather than sending a fabricated fragment. Selection uses public source only; it does not consult relevance labels or held-out observations.

Saved context retains paths, source hashes and exact excerpt ranges. Outbound source JSON removes redundant path metadata when the evidence ID already contains it. Its `lines` pair is an inclusive 1-based range; `sha256` identifies the full source chunk. Excerpts can omit method signatures and branches. Truncation and unrepresented workflow roles remain explicit, and runtime case omissions are recorded separately.

For the standalone source-budget diagnostic, production workflow ranking plus the new packing retains 5/9 labeled create documents, 6/8 read documents and 6/12 update documents. These are development-set document counts; they neither prove semantic coverage nor establish improvements in generated-code outcomes. The actual complete prompt can reserve less source space to accommodate schema and runtime evidence. Supporting setup workflows also compete for that space.

Run the actual prompt audit with:

```powershell
& .\.venv\Scripts\python.exe -m legacylift v2 --home .legacylift audit-prompts
```

[prompt_budget_report.json](../artifacts/v2/prompt_budget_report.json) records all 12 workflow/condition combinations, including the combined `all` workflow. The audit makes no provider request, records prompt hashes and source spans, and reads guidance only. The 16,000-byte limit covers the UTF-8 user prompt, including instructions and evidence context. Provider JSON schemas, system messages and HTTP wrappers are additional; it is not a tokenizer or provider-wide request-size guarantee.

| Workflow | Source only bytes | Runtime only bytes | Hybrid bytes | Hybrid source excerpts | Hybrid guidance cases |
|---|---:|---:|---:|---:|---:|
| Read | 14,020 | 12,274 | 15,937 | 6 | 6/6 |
| Create | 13,770 | 11,304 | 15,980 | 6 | 6/6 |
| Update | 13,729 | 12,351 | 15,966 | 6 | 6/6 |
| All | 15,555 | 13,638 | 15,836 | 5 | 7/18 |

The previous combined hybrid prompt exceeded the limit. The new allocation reserves space for source by lowering that variant's runtime-evidence budget; omitted guidance IDs remain explicit. It is still a reduced evidence view, not proof of full application understanding. Existing trial contexts are immutable: these changes require a new trial rather than silently rewriting old prompt provenance.

Runtime view `redmine-issues-response-2` includes the observed `body_empty` flag derived from byte counts. A guidance-only field audit found no omitted JSON paths in the current examples; secret-field filtering remains active. Missing byte-count/body metadata is left unknown rather than guessed.

These measurements do not establish successful migration, functional compatibility, security, or general retrieval quality across other repositories. The generated create trial that scored 2/4 held out remains final and ineligible for repair or seeding; its findings were not used here.
