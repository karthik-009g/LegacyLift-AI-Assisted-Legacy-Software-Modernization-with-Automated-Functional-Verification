# Controlled study 5788dbc46e2a46ef8848d44985a0e583

Audited checkpoint: **5/27 trials recorded**; study state **incomplete**.

Guidance passes: 0. Held-out evaluations: 0. Full-workflow passes: 0.

HTTP reservations: 12/81 maximum. Reported tokens: 63,560. Requests without token usage: 2.

Unrecorded cells are pending, not passes or observed failures. Token totals omit unreported usage. An incomplete study establishes no condition superiority. Compatibility is separate from human approval and security assessment.

## Workflow and condition coverage

| Workflow | Condition | Recorded / planned | Guidance passes | Workflow passes | Requests |
| --- | --- | --- | --- | --- | --- |
| create | source_only | 1 / 3 | 0 | 0 | 3 |
| create | runtime_only | 0 / 3 | 0 | 0 | 0 |
| create | hybrid | 1 / 3 | 0 | 0 | 1 |
| read | source_only | 0 / 3 | 0 | 0 | 0 |
| read | runtime_only | 1 / 3 | 0 | 0 | 2 |
| read | hybrid | 0 / 3 | 0 | 0 | 0 |
| update | source_only | 0 / 3 | 0 | 0 | 0 |
| update | runtime_only | 0 / 3 | 0 | 0 | 0 |
| update | hybrid | 2 / 3 | 0 | 0 | 6 |

## Recorded outcomes

| Run | Workflow | Condition | Status | Final guidance | Held-out |
| --- | --- | --- | --- | --- | --- |
| a11da6bc27db434d83e230b1db9b782f | update | hybrid | compatibility_failed | 5/6 | not evaluated |
| 8942ec8a5d7148a8ac0318bf78f58810 | create | source_only | candidate_boot_failed | not replayed | not evaluated |
| d4be989bb01d42a09c835f9a053bc390 | read | runtime_only | provider_failed | not replayed | not evaluated |
| c733d3e9d4854ba6a58c0281b319bd8a | update | hybrid | static_review_blocked | not replayed | not evaluated |
| 47cd7dd900b248fd925c5dc468642de3 | create | hybrid | provider_failed | not replayed | not evaluated |

[Audited source report](report-005.json); [trial CSV](trials-005.csv).

A boot/static rejection with no replay is not labelled 0/6. Held-out failures remain final; no hidden mismatch payload is exported here.
