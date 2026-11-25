# Free cloud model options

**23 November steering:** use the existing Groq/Gemini keys; the user deferred OpenRouter setup. It is optional future research, not a prerequisite. Explicit Gemini now shares the larger 48 KB/12K-output profile. Gemini 3.5 Flash-Lite produced a create candidate matching 6/6 guidance after one repair; held-out remains pending. Initial thinking is low and repair thinking is medium after high exhausted the output cap. Keep failed requests and original lineage budgets. [Current evidence](session-2026-11-23.md).

Checked 22 November 2026. LegacyLift uses hosted APIs; it does not require a local LLM. Credentials belong in the ignored local `.env`, never in candidate containers or exports.

## Why add another provider

The current Groq account's 8K-token-per-minute allowance constrains an individual prompt plus reserved completion. A large advertised context window does not remove that allowance. The measured working profile therefore limits hybrid prompts to 14 KB and structured completions to 4,000 tokens, with 65-second pacing. A medium-reasoning create attempt exhausted that completion limit without returning a complete document; its failure remains recorded.

The optional OpenRouter profile admits **48,000 UTF-8 prompt bytes**, up to **26,000 bytes of original guidance**, **12,000 bytes of source excerpts**, **12,000 completion tokens**, and larger checksum-bound repair windows. These are project limits, not a claim that bytes equal tokens. Context and model identity are saved with each run. Guidance/held-out separation, three-request lineage limits, static review and independent Docker comparison are unchanged.

## Explicit models

The [official model catalog](https://openrouter.ai/api/v1/models) listed these zero-price routes with structured-output support at this check. The local catalog snapshot is `.legacylift/provider-catalogs/openrouter-20261122.json`.

| Model ID | Catalog context capacity | Configuration |
| --- | ---: | --- |
| `nvidia/nemotron-3.5-super-vl:free` | 1,000,000 tokens | Default |
| `inclusionai/ling-3.2-flash:free` | 1,048,576 tokens | Optional explicit model |
| `baidu/ernie-5.5-flash-preview:free` | 1,024,000 tokens | Optional explicit model |

These are capacity/availability observations, not measured migration-quality rankings. An actual LegacyLift candidate must pass the same workflow checks before being called successful. Free endpoint availability can change. OpenRouter's [free plan](https://openrouter.ai/pricing) advertises 50 daily requests; account and upstream limits still apply. No credit purchase is required by this integration.

## Setup and use

Add a free OpenRouter key locally, without pasting it into chat:

```dotenv
OPENROUTER_API_KEY="your_actual_key"
LEGACYLIFT_OPENROUTER_MODEL=nvidia/nemotron-3.5-super-vl:free
```

The model setting is optional. To choose another supported model, use its exact ID from the table. Process environment settings take precedence over `.env`. API processes using queued execution can load public model settings without loading provider keys; the worker loads the key when needed.

First run the offline audit:

```powershell
& .\.venv\Scripts\python.exe -m legacylift v2 --home .legacylift audit-prompts --provider openrouter --output .legacylift/verification/openrouter-profile.json
```

Then choose **OpenRouter · free models, larger requests** in the workbench, or use:

```powershell
& .\.venv\Scripts\python.exe -m legacylift v2 --home .legacylift migrate --provider openrouter --workflow create --condition hybrid --max-repairs 2
```

Each trial fixes its requested model; changing it requires a fresh trial rather than rewriting previous provenance. Existing auto mode retains Groq → Gemini fallback and the smaller profile. A large OpenRouter request does not fall through to a paid route or to an incompatible smaller provider budget.

## Free-only enforcement

Before reserving a completion, the client fetches the public catalog without authorization headers. It checks the allowlisted `:free` ID, zero input/output/request prices, structured-output support, context capacity and output capacity. Missing or malformed metadata stops generation. The completion request also sets `provider.max_price` to zero, requires supported parameters, and disables fallback beyond the chosen routing preference. A returned nonzero cost stops the trial. Catalog evidence, serving-provider metadata, request parameters, response schema hash and actual usage are recorded without keys. HTTP quota failures preserve the run and request ledger.

The wire schema constrains evidence citations to IDs actually supplied in that request. A second client-side membership check and the pipeline's existing citation check remain in place. Schema conformity does not prove that a cited chunk supports the model's interpretation.

[OpenRouter routing controls](https://openrouter.ai/docs/guides/routing/provider-selection) describe zero-price caps and parameter requirements. [Groq's structured-output documentation](https://console.groq.com/docs/structured-outputs) documents enum constraints used for citations.

Cerebras was considered because its published token rates are higher, but its [current rate-limit/FAQ page](https://inference-docs.cerebras.ai/support/rate-limits) describes a $5, 30-day trial requiring a verified payment method and explicitly says there is no recurring free tier. It was not selected for the user's free-only requirement.

## Verification status

The adapter, wire-format guards, UI option, profile, persistent call ledger and controlled-study integration are implemented locally. Focused Python tests and the frontend production build passed during implementation. The real larger-provider migration remains pending a configured key and the final checks recorded in RESUME.md. Do not describe mock transport tests as successful hosted migration calls.
