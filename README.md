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

## Setup and local checks

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
ruff check .
ruff format --check .
```

Start the local reference app with:

```powershell
flask --app legacylift.legacy_app.app:create_app run --debug
```

The local SQLite database is stored under Flask's `instance` directory. Set `LEGACYLIFT_SECRET_KEY` when running outside a disposable local environment.

## Development Roadmap

- [x] Python project bootstrap and deterministic Flask/SQLite reference workflows
- [x] Runtime behaviour capture with a versioned synthetic trace
- [x] Static source-code analysis and versioned Engineering Evidence Record
- [ ] FastAPI reconstruction behind a provider-independent interface
- [ ] Differential comparison of responses and state changes
- [ ] Controlled evaluation and reproducible report

---

## Project Status

<kbd>Currently in development</kbd>

Milestones 0 through 3 are complete. The repository contains the Python project setup, deterministic Flask/SQLite reference workflows, repeatable runtime traces, a best-effort AST report, and a validated Engineering Evidence Record. FastAPI reconstruction, differential verification, and evaluation are planned next.

The project is being built incrementally so that each reconstructed implementation can be compared with observable behaviour from its reference workflow.

---

## Motivation

I am interested in building AI systems that solve practical software engineering problems rather than limiting AI applications to text generation or API wrappers.

With LegacyLift, I want to explore the intersection of **AI Engineering, Backend Development, Software Analysis, and Automated Testing**, while understanding the reliability challenges involved in applying LLMs to real-world engineering workflows.

The goal is simple: make legacy software modernization more systematic, evidence-driven, and measurable.

