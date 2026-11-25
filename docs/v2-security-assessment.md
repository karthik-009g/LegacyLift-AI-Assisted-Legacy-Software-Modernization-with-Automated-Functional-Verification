# LegacyLift v2 security assessment

## Static policy remeasured — 24 November 2026

The public OSV check of the controller, build and target lockfiles found zero known advisories across 48 pinned package versions, with zero lookup errors. [Dated Python advisory report](../artifacts/v2/python_dependency_advisories_20261124.json). This measures Python distributions in those locks. The image package findings require their own applicability review.

The current `2.4-capability-references` policy blocked all seven prohibited specimens in the existing eight-specimen assessment, including the three alias/reflection cases missed by the historical policy. The ordinary application passed. The immutable report is [the 24 November assessment](../artifacts/v2/static_policy_assessment_20261124.json). This was a source-only assessment with zero provider requests and no candidate execution. It closes the three documented specimen misses for this policy version. The curated sample and runtime trust limits still apply. Older paragraphs below preserve their measurement dates.

## Dependency finding rechecked — 22 November 2026

The official npm registry still reports picomatch **4.0.7** as latest, but a fresh all-dependency `npm audit --json --ignore-scripts --registry=https://registry.npmjs.org` returned **exit 0 and zero reported vulnerabilities**. The exact local output is preserved at `.legacylift/verification/npm_audit_20261122.json`.

The [GitHub advisory record for GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf) marks it withdrawn on 18 November 2026 and explains that it was not a security issue. This reconciles the disappearance of the earlier five propagated npm entries. No package version, lockfile or source was changed for this recheck. The earlier dated audit below remains preserved as historical measurement. This closes that specific npm advisory finding; it does not close the separate target-image/OpenSSL applicability work or certify the application secure.

The paragraphs below retain their original measurement dates. References to the npm finding as open describe those older checkpoints.

Measured **18 November 2026**. This is a local development assessment with an open dependency finding. Compatibility, container controls, dependency advisories and human source approval are separate claims. None establishes a security certification.

Public metadata was rechecked on **19 November 2026**. The npm registry still lists picomatch 4.0.7 as latest. Debian still lists OpenSSL trixie security 3.5.7-1~deb13u3 and the reviewed vulnerabilities as open. No compatible remediation was adopted from these checks. The 18 November scan results remain dated measurements. [npm package metadata](https://registry.npmjs.org/picomatch/latest), [Debian OpenSSL tracker](https://security-tracker.debian.org/tracker/source-package/openssl).

## Trust boundary

The controller, Docker daemon, host kernel, pinned images and trusted driver are trusted. Legacy and generated application code execute in disposable restricted containers. Model keys belong only to the host-side generation client. Application containers receive synthetic databases and synthetic actor tokens, never provider credentials or held-out expectations. Candidate and driver share writable synthetic state; they are not separate security principals. The local study seal detects consistency changes, not a privileged owner rewriting all data and checksums.

The API/workbench is a local research tool. This assessment does not establish multiuser access control, hardened public hosting, or complete resistance to source/prompt injection, Python obfuscation or container escapes.

## Measured container controls

Run from the project environment:

```powershell
& .\.venv\Scripts\python.exe scripts/assess_runtime_isolation.py
```

`modernization/security_assessment.py` starts a trusted minimal diagnostic FastAPI application through the real PythonTarget adapter, creates a new tiny synthetic database/actor token, inspects Docker configuration, and executes a fixed diagnostic probe as container UID 999. It never opens project fixtures, oracles or .env. A randomly generated host environment sentinel checks that host credentials are not inherited. It restores the sentinel and removes only its owned container on exit. The script is a developer entry point; the reusable module holds the measurement/assessment logic. No new dependency was added.

Actual result: **16/16 controls passed**, [runtime report](../artifacts/v2/runtime_isolation_assessment.json).

| Control | Observation |
| --- | --- |
| Network | Docker network mode none; outbound TEST-NET connection returned Linux ENETUNREACH (101) |
| Exposure | No published ports or host/volume mounts |
| Identity | UID 999; configured user 999:999; privileged false |
| Capabilities | All dropped, no added capabilities; effective capabilities zero |
| Privilege escalation | no-new-privileges and active seccomp filter observed |
| Filesystem | Read-only root; write in /candidate returned EROFS (30); disposable /state remained writable |
| Resource limits | Docker configuration and cgroup v2 files agree: memory 805306368 bytes, 96 PIDs, CPU quota/period 100000/100000 |
| Credentials and sensitive paths | Provider/cloud credential names and the host sentinel absent; no tested Docker socket/.env/oracle path visible |

The probes are intentionally nondestructive. Resource exhaustion, host-kernel exploitation and arbitrary generated-code penetration testing were not performed. Unit regressions reject absent evidence, writable/privileged configurations, host mounts/ports, credential exposure, unbounded cgroups and inconclusive network/filesystem errors. A dedicated Docker-gated test repeats the real measurement.

## Static policy coverage measured on 19 November

`scripts/assess_static_policy.py` parses eight inert source specimens through the current AST policy and writes an immutable dated report. It executes no candidate, makes no provider request and opens no fixture/oracle. Four direct prohibited-capability specimens were blocked, while three equivalent alias/reflection forms passed static review. The ordinary FastAPI control passed. [Actual specimen report](../artifacts/v2/static_policy_assessment_20261119.json).

The missed forms are assigning eval to a different name, assigning the dynamic importer to another name, and reflecting an OS shell method through getattr. These are open static-policy gaps. They do not demonstrate runtime command success or a container escape. Docker restrictions remain required for all generated execution. Fix and remeasure these forms in a subsequent protocol version, preserving the running study's code and its original findings. This small curated set does not establish exhaustive adversarial coverage.

The working-tree policy was subsequently versioned to **2.4-capability-references**. It rejects prohibited callable references before aliasing, from-import aliases and literal getattr access. Seven regressions cover six prohibited forms, approval rejection and accepted ordinary callbacks/reflection. The same eight specimens now show **zero static misses**, with the ordinary app accepted. [Policy 2.4 assessment](../artifacts/v2/static_policy_assessment_v24_20261119.json). The controlled study continues under its preserved policy 2.3 and retains its original limitations. Computed names and other Python obfuscation remain outside this curated coverage. Full Docker validation of the development change is running; current live handles are in RESUME.md.

## Published dependency advisories

`scripts/audit_python_dependencies.py` queries the release-specific [PyPI JSON API](https://docs.pypi.org/api/json/) for every exact package/version pin in controller/development, build and target locks. It validates all pins before requests, deduplicates across locks, verifies response identity, and preserves failed/malformed lookups as incomplete coverage. It installs/resolves nothing and reads no credentials. Eight simulated HTTP tests cover these guarantees.

```powershell
& .\.venv\Scripts\python.exe scripts/audit_python_dependencies.py
Set-Location web
npm audit --json --ignore-scripts --registry=https://registry.npmjs.org
npm audit --omit=dev --json --ignore-scripts --registry=https://registry.npmjs.org
```

| Audit | Actual result | Evidence |
| --- | --- | --- |
| Python exact pins | 48 package/version pairs checked; zero published advisories; zero lookup errors | [Python report](../artifacts/v2/python_dependency_advisories.json) |
| npm, all dependencies | Five high-severity dependency entries, one underlying picomatch advisory; command exit 1 | [All-dependency report](../artifacts/v2/npm_dependency_advisories.json) |
| npm, production dependencies | Zero reported vulnerabilities; command exit 0 | [Production report](../artifacts/v2/npm_production_dependency_advisories.json) |

### Open finding: picomatch development toolchain

The registry audit reports **GHSA-fc5q-39xc-vjpf / CVE-2026-112366**, a repeated-extglob regular-expression denial of service in picomatch through 4.0.7. npm propagates the finding through fdir, tinyglobby, Vite and @vitejs/plugin-react, producing five entries rather than five independent vulnerabilities. The recorded audit contains the advisory URL and affected ranges.

At this check, the public npm registry listed latest picomatch **4.0.7**; querying **4.0.8** returned 404. A compatible published fix was therefore unavailable in these checks. No dependency was downgraded and no unreviewed upstream patch was vendored. The open [upstream PR #194](https://github.com/micromatch/picomatch/pull/194) explicitly says it is not a security fix; its presence does not close this finding.

Observed exposure is the development/build toolchain: the production-only audit is clean, package scripts bind development/preview to 127.0.0.1, and the workbench source contains no direct picomatch/tinyglobby calls or dynamic import.meta.glob. Imported legacy repositories are kept under controller storage, not built as workbench source. These observations narrow the local workflow's exposure; they do not prove non-exploitability or erase the audit finding. Recheck for a compatible published patch and rerun build/browser/audits before release.

## Image advisories and installed-package triage

Ran the already installed Docker Scout 1.27.0 against the cached images with `local://`, SARIF output and --exit-code. Both commands returned 2 because findings exist. No repository analysis was enabled, image was published or subscription changed. Docker documents [one-off local image analysis](https://docs.docker.com/scout/explore/analysis/); this is separate from a stored cloud repository integration.

| Image | Indexed packages | Packages with findings | Reported advisory IDs | Severity by advisory rule |
| --- | --- | --- | --- | --- |
| Trusted target base | 161 | 17 | 51 | 14 high, 9 medium, 28 low |
| Historical Redmine reference | 488 | 43 | 329 | 17 critical, 119 high, 146 medium, 36 low, 11 unspecified |

[Image summary](../artifacts/v2/image_dependency_advisories.json) binds exact image IDs and raw SARIF hashes. Large raw reports are preserved under ignored `.legacylift/security/20261118/`; the reference SARIF has 332 result rows for 329 advisory rules. Advisory aliases and package locations may overlap; these counts are not counts of distinct exploitable flaws. Scanner matches need applicability triage.

Twelve target advisory rules list a fixed version. Findings include Debian zlib and bundled package metadata for setuptools, urllib3 and msgpack. A restricted, trusted metadata-only target container confirmed **17 visible installed Python distributions**, including pip 26.2.2 and no separately installed setuptools. Its exact-version PyPI audit returned zero known advisories/errors. See [installed inventory](../artifacts/v2/target_installed_python_inventory.json) and [installed-package audit](../artifacts/v2/target_installed_python_advisories.json).

This does not dismiss the image scan: for example, the setuptools result points to `/usr/local/lib/python3.14/site-packages/pip/_vendor/bom.cdx.json`. Vendored/bootstrap components differ from the top-level distributions in requirements locks. Their runtime reachability still requires investigation. A zero-finding lock audit cannot close image-only findings.

The target needs a separately versioned hardening candidate: assess an updated pinned Python 3.14 base, security-fixed OS packages and unused installer/bootstrap components, then rescan and replay the trusted functional baseline. Keep the current controlled study's images/code unchanged; any adopted runtime change requires new provenance and a new study version. Do not update the historical reference to make its count look better: that would change the behavior being measured. Its old dependencies remain isolated and outside public serving.

## Verified hardening proposal at the requested pause

Development paused at the user's request on 18 November. The independent [proposal report](../artifacts/v2/target_hardening_proposal.json) records image 9758815f421d442492d80241f65a3d8b as **verified, unadopted, with open findings**. It leaves Python 3.14.10 and study source/images unchanged, installs exact Debian zlib security revision deb13u1, and removes unused pip/ensurepip installer archives after dependencies. Six tool-guard tests passed. Real checks passed 16/16 isolation, 4/4 engineered guidance and 7/7 source mutants; the four-case capture hash is identical. This is not a model or held-out success.

Scanner rules decreased 51→39 and high labels 14→6, with twelve removed and zero new rules. Raw before/after reports remain hash-bound; aliases and product attribution still need care. [The attribution review](../artifacts/v2/advisory_attribution_review.json) records conflicting primary sources for CVE-2026-76844. No verified resolution of that disputed ID is inferred from its removal.

[Residual OpenSSL review](../artifacts/v2/openssl_applicability_review.json) records six remaining entries, each labelled High by Scout and Low by [OpenSSL's primary vulnerability list](https://openssl-library.org/news/vulnerabilities/), with upstream 3.5.10 fixes. [Debian's source tracker](https://security-tracker.debian.org/tracker/source-package/openssl) still lists the installed 3.5.7-1~deb13u3 as its security version. The affected features concern CMS, QUIC, PEM-stack and AES-GCM-SIV operations. The current HTTP-only loopback/network-none profile constrains exposure; it does not prove arbitrary generated code cannot reach those APIs. Findings stay open for exact-candidate review/vendor remediation. No scanner label was suppressed, no security exception was approved, and no image was silently adopted into the frozen study.

The build uses an exact OS version and signed live APT metadata rather than a Debian snapshot mirror. Preserve this reproduction limitation. Continue from RESUME/handoff Section 32 only after the user resumes.

## Remaining assessment

The [25 November exact-update review](../artifacts/v2/openssl_applicability_review_20261125.json) binds the inspected image and approved source checksum. It found no selected direct affected API names in that source; indirect reachability is unproven, and future read/create sources need separate review. OpenSSL runtime is 3.5.7 / Debian package 3.5.7-1~deb13u3. Vendor findings stay open. See [Debian's tracker](https://security-tracker.debian.org/tracker/source-package/openssl) and [OpenSSL's list](https://openssl-library.org/news/vulnerabilities/). No scanner suppression, image adoption or study rewrite occurred.

Image findings and the npm development advisory remain open. Broad application penetration testing, dependency provenance verification, prompt-injection campaigns and public deployment hardening remain open. Existing authorization/audit mutation tests demonstrate fault detection in this finite study, not complete application security. A real model-generated candidate still needs independent guidance/held-out verification and checksum-bound human source review before export.
