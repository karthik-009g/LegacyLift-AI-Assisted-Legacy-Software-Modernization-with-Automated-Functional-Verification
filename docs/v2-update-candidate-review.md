# Review the generated Redmine issue update

The [recorded local walkthrough](../.legacylift/verification/approved-update-browser-20261123.webm) opens the genuine approved run, shows both verification reports and downloads the reviewed ZIP. The browser test compared the downloaded bytes and ETag with the API response and confirmed that the source, report and approval stayed the same.

**Release replay, 23 November 2026.** Existing approval remains intact. The genuine saved-run browser test showed 6/6 + 4/4 and downloaded the same bytes as the API. The exact source from the new deterministic ZIP replayed 6/6 + 4/4 in Docker. [Reproducible export](../.legacylift/exports/legacylift-update-664dedff-reproducible.zip), SHA-256 `62897503097adb389240897433817b7528594476f811542f2f938baaafd6c473`. Original ZIP below is preserved. This changes packaging, not source or approval.

**Approved and exported, 22 November 2026.** The user approved this exact candidate as reviewer **goku**, with the note: “everything is fine but model usage is bit cramped so i think we should add more models with better token limit”. Approval was recorded through the real workbench API and binds the source and held-out report checksums below. Source and reports were not changed. The checked ZIP includes code, target dependency lock, verification, review, README and GPL COPYING notice. [Local export](../.legacylift/exports/legacylift-update-664dedff.zip); receipt: `.legacylift/exports/update-approval-20261122.json`. ZIP SHA-256: `c648535ae0cb75f494b7db1a7e763edd6af5616a897cfacab2208cc04266abd0`. This approval covers the local selected-workflow demo and does not certify production security.

Run **664dedffc38744058e786f61c65d0f25**, verified on 21 November 2026. Groq GPT-OSS 120B generated the candidate in one request from update/hybrid evidence. No author edited the generated source between creation, guidance replay, and held-out replay.

| Check | Result |
| --- | --- |
| Static policy check | Passed |
| Guidance replay | 6/6 scenarios matched |
| Held-out replay | 4/4 scenarios matched |
| Model usage | 3,762 prompt tokens and 2,404 completion tokens |
| Human approval | Approved by goku, 22 November 2026 |

Open the [exact source](../.legacylift/runs/664dedffc38744058e786f61c65d0f25/app.py), [guidance report](../.legacylift/runs/664dedffc38744058e786f61c65d0f25/guidance-0.json), and [held-out report](../.legacylift/runs/664dedffc38744058e786f61c65d0f25/held-out.json) in the local workspace. Functional checks compare HTTP responses and the issue, journal, and journal detail records with the pinned Redmine 4.2.10 reference in isolated Docker runtimes.

- Source checksum: d81331cc44c4a2bd59deb29fc6338bbcb03442ec37220f8ef92da722d8a18abc
- Held-out report checksum: 9f86540675ccf0df5cdfefbcd2762b1ce9c8c7537d6c3e060d4e588dca6d1858

The review is for the local issue update demonstration with the synthetic fixture. Check the API-token lookup, project membership and role checks, allowed status transitions, issue and journal writes, fixture clock, and empty success/error responses. The source uses bound query parameters for request values. Its transition query filters by role and status, and omits tracker-specific rules and broader role behavior. The results cover the declared scenarios. Broader tracker combinations, concurrency, and arbitrary request bodies still need verification for production use. Retain Redmine's GPL attribution on export.

Select this run in the workbench to see the existing goku approval and download the reviewed source. Do not repeat approval for this unchanged candidate. Keep the recorded source, both reports and the export receipt together for the case study.
