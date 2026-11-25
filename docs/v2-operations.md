# LegacyLift v2 local operations

For larger free-model requests, see [OpenRouter setup and model choices](free-model-providers.md). Select `--provider openrouter` or the workbench's free-model option; the client enforces explicit zero-price routes. Groq/Gemini retain their existing auto path and budgets.

LegacyLift v2 migrates selected Redmine 4.2.10 Ruby/Rails workflows to Python/FastAPI and compares the result against a frozen reference. The workbench is a local research tool; a completed job is not a verified migration, and compatibility is not a security certification.

## Local setup

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --no-deps --requirement requirements-build.lock
python -m pip install --no-deps --requirement requirements.lock
python -m pip install --no-deps --no-build-isolation --editable .
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Add provider keys to the ignored `.env` only if you want model-generated candidates. Groq is tried first and the configured Gemini model is the backup. The CLI records safe provider/model, usage, timing and prompt-hash metadata; it never writes API keys into run artifacts. The provider tier is an account setting and cannot be verified by this application.

## Build and run the workbench

### Staged generation and saved retries

In **Migration**, choose **Read & visibility**, **Source + runtime**, and a fixed **Groq** or **Gemini** provider to enable **Separate endpoints · experimental**. Combined generation remains the default. Separate endpoints generate GET and POST independently within the same three-request limit; failures and repairs count toward that limit. Groq additionally exposes low/medium/high reasoning selection. The experimental label reflects that this path still requires successful functional verification; exposing the control does not establish migration correctness.

A saved run restores its generation mode/reasoning controls. **Retry failed provider call** uses that run's saved provider, mode and reasoning, even if the new-run form is edited. The API also infers omitted saved settings and rejects changes before queueing. Request usage is shown from the durable ledger. Once exhausted, the UI removes retry and the API refuses it; the last compatibility/static-review verdict remains visible.

New migration job parameters are `staged_read: true` and, for staged Groq only, `groq_reasoning_effort: "low" | "medium" | "high"`. Unsupported workflow/evidence/provider combinations return 422. Changed saved settings or an exhausted retry return 409. The job worker forwards the validated settings to the migration pipeline. Run details expose only the selected generation settings, not the complete evidence context.

Browser tests queue/cancel settings against a disposable API with job execution disabled, and separately verify saved retry payloads/exhausted UI. These are workbench integration checks, not model-migration results. Genuine approved-source browser checks only read/export the existing reviewed candidate and do not generate, finalize or approve a new one.

### Start the local server

Build the React client once:

```powershell
Push-Location web
npm ci
npm run build
Pop-Location
$env:LEGACYLIFT_WEB_DIST = (Resolve-Path web/dist).Path
```

In the repository root, prepare the pinned reference and start the local workbench:

```powershell
python -m legacylift v2 --home .legacylift prepare
python -m legacylift v2 --home .legacylift serve
```

Open `http://127.0.0.1:8010`. Preparation downloads the pinned public source when needed, starts the isolated Redmine reference using Docker, captures the synthetic fixture, and builds Ruby evidence. It makes no model request. Keep the API bound to loopback.

Docker is used to run the pinned reference and each generated candidate in isolated containers. The UI/API process and its optional local worker run on the host. No application container is given the Docker socket or provider keys. Candidate containers have no network, a read-only root filesystem, dropped Linux capabilities and bounded CPU/memory/process counts.

## Optional Postgres and Valkey

The default local mode needs no Compose stack: it stores workbench metadata in SQLite and runs one background worker in the API process. For durable metadata and queued jobs, Compose starts only loopback-bound Postgres and Valkey services:

```powershell
docker compose up -d postgres valkey
$pgPort = ((docker compose port postgres 5432) -split ':')[-1]
$redisPort = ((docker compose port valkey 6379) -split ':')[-1]
$env:LEGACYLIFT_DATABASE_URL = "postgresql+psycopg://legacylift:local-only-change-me@127.0.0.1:$pgPort/legacylift"
$env:LEGACYLIFT_REDIS_URL = "redis://127.0.0.1:$redisPort/0"
```

Compose assigns ephemeral host ports on loopback so startup works when the usual database ports are reserved by Windows or another service. Run `docker compose ps` to confirm both services are healthy before starting the API and worker.

Run the API in one PowerShell window and the host-side RQ worker in another. The queued API process loads the database/queue settings but does not load model keys; the separate host worker loads the keys it needs:

```powershell
python -m legacylift v2 --home .legacylift serve
python -m legacylift v2 --home .legacylift worker
```

Only the host-side worker loads provider keys from `.env`; the queued API process does not. Keep `.env` private and use free-tier accounts for this project. The fallback Postgres password is for loopback-only development and must be replaced before any network-exposed deployment. Stop the optional services with `docker compose down`; `docker compose down -v` also deletes their stored data.

## Migration and verification

Run the local guidance-only mutation campaign to check that the comparator detects deliberate authorization, validation, response-header/body, database-state and audit changes. It reads the frozen guidance oracle, runs no candidate code, sends no provider request and never opens held-out observations:

```powershell
python -m legacylift v2 --home .legacylift verify-mutations
```

The report is written to `artifacts/v2/mutation_report.json`. A passing mutation report validates comparator sensitivity; it does not certify a generated migration.

Select a workflow and evidence condition in the UI, then request a migration. Or use the CLI:

```powershell
python -m legacylift v2 --home .legacylift migrate --workflow read --condition hybrid --provider auto --max-repairs 0
```

`--max-repairs` is bounded from zero to two. A provider pause saves a run and never resends an uncertain request implicitly. An explicit retry keeps the same run ID and records an append-only provider-attempt log. If an initial prompt exceeds its budget, narrow the workflow or evidence condition. A repair prompt rejected locally can resume its saved draft with `--run-id ID --retry-failed-call`; no provider call was sent for that rejected repair, and the initial draft is reused.

Only a candidate that passes guidance checks can be finalized against held-out scenarios. Held-out results do not feed back into that run's repair prompt. Human review is tied to the exact candidate checksum; only then can the reviewed bundle be exported. Generated artifacts and the synthetic database stay under ignored `.legacylift/`.

Real HTTP attempts now share a persistent three-request cap across each seed lineage, including fallback providers and uncertain requests. A failed request cannot gain a fresh budget by moving to another seeded run. Preparation seals the reference artifacts, and guidance replay opens the separately checksummed guidance file rather than the combined oracle. Existing frozen workspaces can run `v2 seal-study` once. See [the controlled-evaluation protocol](v2-controlled-evaluation.md) for request audits and prospective planning; that study has not executed.

## Local checks

```powershell
python -m pip check
ruff check src tests
ruff format --check src tests
python -m pytest -q
Push-Location web
npm run build
Pop-Location
```

To include the Docker candidate smoke test after building the evaluator image, set `LEGACYLIFT_DOCKER_SMOKE=1` for that pytest run. GitHub Actions and public deployment are deliberately outside local development.

To exercise the browser review/export workflow end to end, run this from `web/`:

```powershell
npm run test:e2e:review
```

This builds the frontend and starts a disposable loopback API with an explicitly labeled synthetic candidate, synthetic guidance/held-out summaries, and an isolated temporary metadata database. It exercises the real UI, approval endpoint, and ZIP download; it makes no model request and does not read or alter `.legacylift/`. The displayed pass is test plumbing only, never evidence that a Redmine migration passed.

The runner type-checks its test/configuration files, refuses to reuse a server on port 8011, and stops its owned API process before removing the generated fixture. On Windows this ordering prevents SQLite file-lock cleanup failures.

To measure source retrieval without a provider call or application runtime:

```powershell
& .\.venv\Scripts\python.exe -m legacylift v2 --home .legacylift evaluate-retrieval
```

See [the retrieval diagnostic](v2-retrieval-evaluation.md) for the development labels, BM25/workflow/dependency comparison, generation-budget limitation and report provenance.

Before a new generation trial, check all 12 prompt variants without sending them:

```powershell
& .\.venv\Scripts\python.exe -m legacylift v2 --home .legacylift audit-prompts
```

This checks the 16 KB UTF-8 user-prompt cap, including instructions and evidence. It records exact source spans and omitted source roles/guidance cases. Provider schemas and system-message wrappers are outside this local prompt cap. A changed evidence index or packing version requires a new trial; saved trial contexts are immutable.
