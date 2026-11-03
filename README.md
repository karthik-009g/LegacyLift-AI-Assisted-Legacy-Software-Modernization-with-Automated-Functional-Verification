# LegacyLift
### AI-Assisted Legacy Software Modernization with Automated Functional Verification

<p align="center">
  <img src="https://img.shields.io/badge/Status-In%20Development-orange?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Python-3.x-blue?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/AI-Assisted%20Engineering-purple?style=for-the-badge" />
</p>

## About

I am building **LegacyLift** to explore how AI can assist in modernizing legacy web applications without compromising their existing functionality.

Legacy applications often contain complex business logic distributed across source code, API endpoints, session handling, and database operations. Incomplete documentation and limited regression testing make understanding and reconstructing these systems particularly challenging.

My approach is to combine static source-code analysis, runtime behaviour capture, and LLM-assisted reconstruction to understand how an existing application actually works.

Rather than relying on AI-generated code alone, I use an evidence-driven reconstruction process followed by differential testing to compare the original and reconstructed implementations.

The initial focus is on reconstructing selected legacy application workflows as modern FastAPI endpoints and evaluating their behavioural consistency.

---

## What I Am Building

- **Legacy Application Analysis** – Understanding application structure, source-code dependencies, routes, and business logic.
- **Runtime Behaviour Capture** – Collecting HTTP requests and responses, cookies, session information, and database changes.
- **Engineering Evidence Record** – Organizing observed facts, inferred behaviour, API contracts, uncertainties, and validation requirements.
- **AI-Assisted Reconstruction** – Using LLMs to reconstruct selected legacy workflows as FastAPI endpoints.
- **Differential Testing** – Comparing original and reconstructed application behaviour across equivalent test scenarios.
- **Evaluation Framework** – Measuring behavioural fidelity and comparing different evidence-based reconstruction approaches.

---

## How It Works

```text
       Legacy Web Application
                 |
         +-------+-------+
         |               |
   Static Analysis   Runtime Capture
         |               |
         +-------+-------+
                 |
        Engineering Evidence
              Record
                 |
          LLM-Assisted
           Reconstruction
                 |
          FastAPI Endpoints
                 |
         Differential Testing
                 |
       Original vs Reconstructed
                 |
         Verification Results
```

---

## Stack I Work With

### Languages

<p>
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/SQL-000000?style=for-the-badge&logo=postgresql&logoColor=white" />
</p>

### AI / LLM

<p>
  <img src="https://img.shields.io/badge/LLMs-AI%20Integration-8A2BE2?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Prompt%20Engineering-Evidence%20Grounded-black?style=for-the-badge" />
</p>

### Backend

<p>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/REST%20APIs-Backend-blue?style=for-the-badge" />
</p>

### Analysis & Verification

<p>
  <img src="https://img.shields.io/badge/Static%20Analysis-Code%20Inspection-3572A5?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Runtime%20Analysis-Behaviour%20Capture-orange?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Differential%20Testing-Functional%20Verification-green?style=for-the-badge" />
</p>

---

## Evaluation

I want to evaluate LegacyLift based on functional correctness rather than code generation alone.

| Metric | Evaluation Focus |
|---|---|
| Behavioural Fidelity | Agreement between original and reconstructed workflows |
| API Consistency | HTTP status codes, response structures, and values |
| State Consistency | Preservation of workflow state transitions |
| Database Consistency | Equivalence of resulting database changes |
| Evidence Coverage | Contribution of source and runtime evidence |
| Correction Effort | Manual effort required to resolve behavioural differences |

### Experimental Comparison

I also plan to compare three reconstruction strategies:

- **Source-only:** Using static source-code evidence.
- **Runtime-only:** Using observed application behaviour.
- **Combined evidence:** Using both static and runtime evidence.

This will help me evaluate whether combining different evidence sources improves reconstruction quality.

---

## Milestone 1: Deterministic Legacy Reference

The first reference app uses Flask, SQLite, synthetic data, and a reset utility. Its selected stateful workflows are:

- Create a ticket with subject and description validation.
- Retrieve a ticket only when it belongs to the current session user.
- Move a ticket through `open → in_progress → closed`; invalid jumps return a conflict.

`POST /session` sets a synthetic identity for local scenarios. It is not production authentication. The seeded ticket belongs to `alice`. Seven baseline tests cover success, invalid input, ownership, status transitions, persisted database state, and reset behavior.

## Milestone 2: Runtime Capture

The capture runner replays fixed synthetic scenarios against a fresh SQLite fixture database and records each request, response, session transition, redacted cookie metadata, and ticket database snapshot/delta. The versioned sample trace is [`artifacts/traces/ticket_workflows.json`](artifacts/traces/ticket_workflows.json). Cookie values and local session secrets are not stored.

## Milestone 3: Static Analysis and Evidence Record

The AST pass reports literal Flask route decorators, function definitions, imports, branch counts, and session/database references without executing source files. Its report is [`artifacts/static/legacy_analysis.json`](artifacts/static/legacy_analysis.json). A strict Pydantic schema keeps observed facts, inferences, unknowns, captured contracts, validation cases, and provenance separate. The checked-in EER and its JSON Schema are under `artifacts/evidence/` and `artifacts/schemas/`.

## Milestone 4: Reconstruction Baseline and Provider Boundary

The project includes an independently implemented FastAPI ticket service with its own Pydantic request models and SQLite fixture. Its routes are covered by differential tests against the Flask reference. The reconstruction interface accepts bounded, selectable source/runtime evidence (`source_only`, `runtime_only`, or `hybrid`). An optional Groq adapter requests a cloud model proposal; output is saved for review and is not executed automatically. An explicit evaluation command can run code that a person has reviewed inside a restricted Docker container.

## Milestone 5: Differential Verification

The differential runner replays each fixed scenario against fresh Flask and FastAPI databases. It compares response status, selected headers, JSON, cookie attributes (with cookie values redacted), session transitions, database snapshots, and database deltas. Differences are retained by field in the report rather than normalized away. The checked-in result is [`artifacts/verification/differential_report.json`](artifacts/verification/differential_report.json).

Regenerate it with:

```powershell
python -c "from legacylift.verification.runner import write_differential_report; write_differential_report('artifacts/verification/differential_report.json')"
```

## Milestone 6: Held-Out Evaluation

The initial split uses `create_ticket`, `retrieve_owned_ticket`, and `valid_status_transitions` as guidance scenarios. `hide_other_users_ticket`, `reject_empty_subject`, and `reject_skipped_status` are held out from runtime evidence. The evaluation builds and stores a guidance-only trace and EER, audits the source-only/runtime-only/hybrid contexts for held-out runtime leakage, and measures the hand-built FastAPI baseline against the held-out cases.

The baseline matched all 3 held-out scenarios and all 6 request steps. This measures the hand-built implementation only. The source-only, runtime-only, and hybrid model reconstruction comparison has **not been run**: there is no model-generated app for any condition, and the mock provider does not generate executable code. The report makes no claim that one evidence condition performs better. The optional reviewed-candidate runner is implemented; running it still requires three proposals and a person to inspect their code.

The guidance inputs and report are in [`artifacts/evaluation/`](artifacts/evaluation/). Regenerate them with:

```powershell
python -c "from legacylift.evaluation import write_evaluation_artifacts; write_evaluation_artifacts('artifacts/evaluation')"
```

## Optional Groq Cloud Model

The optional provider uses the existing `httpx` dependency and Groq's OpenAI-compatible chat completions API. The default model, `openai/gpt-oss-20b`, supports strict JSON Schema output. Groq documents a Free tier with account-specific limits; keep the account on that tier and do not upgrade to Developer for this project. Groq says upgrading to Developer requires a payment method; see its [billing FAQ](https://console.groq.com/docs/billing-faqs). Limits and model availability can change.

Create a Groq API key in the [Groq Console](https://console.groq.com/keys), then enter it as a secure PowerShell prompt for the current session:

```powershell
$secureKey = Read-Host "Groq API key" -AsSecureString
$env:GROQ_API_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
python -m legacylift propose --condition hybrid
Remove-Item Env:GROQ_API_KEY
Remove-Variable secureKey
```

To prepare all three evidence-condition proposals, run `legacylift propose --condition source_only`, `runtime_only`, and `hybrid` separately while the key is set. Each command makes one external API request and writes its response under the ignored `artifacts/proposals/` directory. The normal `demo` command stays offline. The provider sends the selected EER evidence and, for source-only/hybrid, bounded source excerpts to Groq over HTTPS; use only source you are allowed to share. The API key is read from `GROQ_API_KEY` and is not written to proposal files. The evaluation container does not receive this key.

After generating all three proposals, inspect the `proposed_code` in each JSON file under `artifacts/proposals/`. Build the evaluator image once, then explicitly declare that you reviewed the code:

```powershell
docker build --file Dockerfile.evaluation --tag legacylift-evaluation:py311 .
python -m legacylift evaluate-proposals --human-reviewed
```

This writes `artifacts/proposals/model_generated_comparison.json`. The container has no network, a read-only root filesystem, resource limits, and receives only the candidate file as a read-only mount. This is defense in depth, not a security boundary for hostile code: review each proposal carefully. The image includes LegacyLift source, including the fixed held-out scenario definitions, so the experiment does not prove resistance to an adversarial model inspecting the local evaluator. The report includes scenario/step match rates, response/session/database agreement, model-reported unsupported claims, and a hash of each candidate. Unsupported behaviors and manual correction time remain unmeasured. One run per condition on one synthetic split supports descriptive results only, not a general claim that one evidence condition is better.

### Run through GitHub Actions

If you do not have Docker locally, the repository has two manual workflows. Add `GROQ_API_KEY` under **Settings → Secrets and variables → Actions**. In the Actions tab, run **Generate Groq proposals**. Download its `groq-proposals` artifact, inspect all three `proposed_code` fields, then run **Evaluate reviewed Groq proposals** with that workflow run ID and `human_reviewed` enabled. Download the `model-generated-comparison` report artifact from the second run. Both workflows are manual; generation makes three Groq API requests. This repository is public, so workflow artifacts can be read by people who can access the repository; use only source you are allowed to share.

## Milestone 7: Documentation and End-to-End Demo

The architecture and evidence boundaries are described in [`docs/architecture.md`](docs/architecture.md); the split, metrics, current results, and limits are in [`docs/evaluation.md`](docs/evaluation.md). A labeled, synthetic mismatch example is available at [`artifacts/verification/sample_mismatch.json`](artifacts/verification/sample_mismatch.json). The single-command demo regenerates all checked-in artifacts, runs the differential and held-out checks, then prints a machine-readable summary:

```powershell
python -m legacylift demo
```

GitHub Actions runs the demo, full test suite, lint, formatting, dependency checks, and a generated-artifact freshness check on pushes and pull requests.

## Setup and local checks

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m legacylift demo
python -m pytest
ruff check .
ruff format --check .
python -m pip check
```

The lock file and `.python-version` pin the versions used to generate the committed reports. `pyproject.toml` retains bounded package requirements for normal installation.

Start the local reference app with:

```powershell
flask --app legacylift.legacy_app.app:create_app run --debug
```

The local SQLite database is stored under Flask's `instance` directory. Set `LEGACYLIFT_SECRET_KEY` when running outside a disposable local environment.

## Development Roadmap

- [x] Python project bootstrap and deterministic Flask/SQLite reference workflows
- [x] Runtime behaviour capture with a versioned synthetic trace
- [x] Static source-code analysis and versioned Engineering Evidence Record
- [x] FastAPI reconstruction baseline behind a provider-independent interface
- [x] Differential comparison of responses and state changes
- [x] Reproducible held-out baseline evaluation and evidence-context audit
- [ ] Run and record model-generated source-only/runtime-only/hybrid comparison
- [x] Final documentation and one-command demo

---

## Project Status

<kbd>Currently in development</kbd>

The deterministic prototype, evaluation tooling, and demo are implemented. The report confirms the manually implemented FastAPI baseline matches all current held-out cases and that runtime/hybrid evidence contexts contain guidance traces only. A Groq proposal path and reviewed-candidate container are available, but proposals have not yet been generated and evaluated across the three conditions; the project makes no comparative performance claim.

The project is being built incrementally so that each reconstructed implementation can be compared with observable behaviour from its reference workflow.

---

## Motivation

I am interested in building AI systems that solve practical software engineering problems rather than limiting AI applications to text generation or API wrappers.

With LegacyLift, I want to explore the intersection of **AI Engineering, Backend Development, Software Analysis, and Automated Testing**, while understanding the reliability challenges involved in applying LLMs to real-world engineering workflows.

The goal is simple: make legacy software modernization more systematic, evidence-driven, and measurable.

