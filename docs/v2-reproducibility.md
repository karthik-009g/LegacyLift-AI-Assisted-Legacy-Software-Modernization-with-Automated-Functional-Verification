# Local source-snapshot reproduction

## 24 November 2026

Snapshot `37a33de6db3042cca0901e776a34e5e3` passed all seven locked installation stages and eight reproduction checks. The reference matched the frozen oracle. The installed Python suite passed **457 tests, zero skips**, and frontend review/export browser verification passed. Receipts are `install-verification.json` and `checks-verification.json` beside the snapshot manifest. Logs are `.legacylift/verification/reproduce_install_20261124.log` and `reproduce_checks_20261124.log`. This snapshot contains anchored read evidence and create policy v4, and predates the final read-contract wording clarification. Reproduction used the same Windows host and Docker engine.

## Read adapter v2 and parser-window reproduction

Snapshot `4ddba0bf9d174099b353de65e793d913` completed seven locked installation stages and eight verification stages. A fresh replay matched the frozen oracle and preserved the five observed routes. The full Python suite passed **453 tests with zero skips** across all four Docker gates. The wheel asset check, lint and format checks, locked frontend build and synthetic reviewer browser flow also passed. The saved receipts are `install-verification.json` and `checks-verification.json` next to the snapshot manifest. The snapshot includes the read adapter and first create source policy. Later prompt corrections and grouped diagnostics were tested on the workspace separately.

## 23 November 2026 — fresh install and reference replay

Snapshot `9642959c20a44ca18de660b1d96168bd` captured 331 files with inventory SHA-256 `6f887c8c6ae3fd19eeb4b335ff6d42fb129bbb0d22712852a6f5b54e58f63ed8`. All seven installation stages and eight verification stages passed on the same Windows host. The installed package rebuilt the reference and matched the frozen oracle hash `c2abdccfe9f9ba29d1e60fdf1f98ce7e0ec24d57270af68671a75a53ae09972a`. All four Docker gates ran with **450 Python tests passed and zero skipped**. Frontend lockfile install, build, type check and synthetic browser review/export passed. The installation and check receipts are saved beside the manifest in `.legacylift/reproductions/9642959c20a44ca18de660b1d96168bd/`.

The snapshot includes deterministic exports and transactional repair replay. It predates the read scaffold. A separate real-run recording shows the approved update and verified ZIP on the live workbench. [Local walkthrough](../.legacylift/verification/approved-update-browser-20261123.webm).

## 21 November 2026 — snapshot after the generation and repair refactor

Snapshot **7b24e8435ebf42d2a686e72feb2ba7bb** contains 316 source files. The pinned wheel built and installed in a fresh environment. All seven installation stages and eight verification stages passed. Installed-package verification matched 79 source and asset hashes. The real Redmine replay rebuilt all 30 reference observations and produced oracle checksum c2abdccfe9f9ba29d1e60fdf1f98ce7e0ec24d57270af68671a75a53ae09972a.

The installed snapshot ran **389 Python tests, zero skips**, the lint and format checks, the frontend install and build, and one synthetic browser review/export test in 6.7 seconds. Starlette still reports its existing test-client deprecation, and Vite still reports a large chunk. Model requests were excluded from reproduction. The [verified update candidate](v2-update-candidate-review.md) has a separate workbench API review preflight. The snapshot reused Docker and the browser on the same Windows host.

Logs and manifests are under .legacylift/reproductions/7b24e8435ebf42d2a686e72feb2ba7bb. The 18 November inventory below records the earlier snapshot.

## Earlier reproduction — 18 November 2026

Updated 18 November 2026. This verifies an exact inventory of uncommitted source on the existing Windows host. It is not a published clean Git checkout, independent-machine certification or model-migration result.

## Inputs and build choices

`modernization/source_snapshot.py` lists tracked/untracked nonignored project files through read-only Git, excludes private/local paths (including tracked `.env` variants), rejects unsafe paths/links, copies files to a unique ignored directory and records exact SHA-256 hashes. Unrelated `ion` is preserved. `verify_source_snapshot` checks manifest placement, path safety, inventory count, listed bytes and absence of root provider configuration before use and after checks. Generated dependencies/build files are not original inventory entries.

`requirements-build.lock` pins setuptools 84.2.1, wheel 0.48.0 and packaging 26.3. Versions/default dependencies were checked against official [setuptools](https://pypi.org/project/setuptools/84.2.1/) and [wheel](https://pypi.org/project/wheel/0.48.0/) metadata. Runtime/development versions remain in `requirements.lock`. Installations use `--no-deps`; `pip check` exposes missing/inconsistent closure. Wheel building uses `--no-build-isolation` after installing the explicit build lock. Wheel hashes identify builds; bit-identical wheel archives have not been established.

The snapshot's `.venv` matches the documented application/browser-test layout. The original working environment remains unchanged. Child commands receive a required-tool/Windows/proxy environment allowlist, excluding model credentials, old Python paths, old controller database/queue settings and user pip-index overrides. Public PyPI is configured explicitly. This is process-environment isolation, not a claim that trusted build tools cannot read user-owned host files.

## Procedure

From the original workspace, create the snapshot and note its returned source directory:

```powershell
python -c "from pathlib import Path; from legacylift.modernization.source_snapshot import create_source_snapshot; print(create_source_snapshot(Path.cwd())['source_directory'])"
```

Its manifest is beside `source`. Substitute the exact ID:

```powershell
python scripts/reproduce_install.py .legacylift/reproductions/SNAPSHOT_ID/manifest.json
python scripts/reproduce_checks.py .legacylift/reproductions/SNAPSHOT_ID/manifest.json
```

The installer verifies the inventory, creates a private environment, checks absence of a previous project installation/system-site access, installs exact locks, builds/installs the wheel and checks installed CLI/dependencies. It records commands, durations, exit codes and logs. A recorded attempt is preserved; use a fresh snapshot for another attempt.

The checker requires the exact matching installation. It verifies installed package/assets against archived hashes, prepares the real reference from the wheel, compares the reference checksum with the existing seal when available, builds the v1 evaluator, runs Python tests with all four Docker gates, runs lint/format checks, installs frontend dependencies from the lock and runs production build/type/browser review-export checks. No model generation request occurs. Browser data is synthetic.

Prerequisites: Python 3.11+, Git, Node/npm, Edge for the browser configuration, a running Docker Linux engine, and network access for uncached public packages/source/images. Existing host Docker/browser binaries and caches are reused; this is not a new operating-system installation.

## Preserved attempts

| Snapshot | Measured result |
|---|---|
| `a080853ac7194ff58736ab477111e306` | Original 186-file snapshot only. |
| `63e02f546e61477394d7377756306055` | 187 files; seven install stages and 76 installed file comparisons passed; reference extraction FAILED on a long Windows path. |
| `38868199da0c49e68d4d2e20f54899a0` | 189 files including the fix; installation passed and 30 observations reproduced the saved reference checksum. Exact executed installer source preserved. |
| `ee5c3b3152f444f19193f52371226b19` | 190-file snapshot; seven installation stages and nine verification stages passed. 277 Python tests, zero skips, lint/format (95 files), frontend install/build/type checks and one synthetic browser review/export test passed. |

The reproduced canonical reference hash is `c2abdccfe9f9ba29d1e60fdf1f98ce7e0ec24d57270af68671a75a53ae09972a`. Actual fresh extraction exposed Windows normal-path length limits. `repository.native_source_path` now uses native extended source paths on Windows while retaining archive traversal/link protections and scoped cleanup. Tests exercise actual >260-character extraction, Ruby analysis and failure cleanup. No Windows global long-path policy was changed.

Private snapshots/logs live under `.legacylift/reproductions/`. Publish selected key-free summaries only; keep fixtures/oracles/actor data private. Preserve failures and inspect real JSON/logs before reporting success. These checks do not establish actual controlled-model outcomes or positive migrations.

The [selected reproduction report](../artifacts/v2/source_snapshot_reproduction.json) records the snapshot inventory and wheel hashes. Python checks took 129.68 seconds; browser verification passed in 6.4 seconds. All 76 installed package/asset files matched archived source bytes. A supplementary installed-CLI audit checked all 12 real prompt variants with output outside the immutable source inventory. No LegacyLift-owned containers remained afterward. Existing Starlette/httpx and Monaco chunk warnings remain. Subsequent generation-contract changes have their own tests and are not retroactively part of this snapshot's evidence.
