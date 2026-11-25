# Controlled study 5788dbc46e2a46ef8848d44985a0e583

Audited checkpoint: **23/27 trials recorded**; study state **incomplete**.

Guidance passes: 0. Held-out evaluations: 0. Full-workflow passes: 0.

HTTP reservations: 55/81 maximum. Reported tokens: 283,915. Requests without token usage: 12.

Unrecorded cells are pending, not passes or observed failures. Token totals omit unreported usage. An incomplete study establishes no condition superiority. Compatibility is separate from human approval and security assessment.

## Workflow and condition coverage

| Workflow | Condition | Recorded / planned | Guidance passes | Workflow passes | Requests |
| --- | --- | --- | --- | --- | --- |
| create | source_only | 2 / 3 | 0 | 0 | 6 |
| create | runtime_only | 3 / 3 | 0 | 0 | 8 |
| create | hybrid | 3 / 3 | 0 | 0 | 5 |
| read | source_only | 2 / 3 | 0 | 0 | 3 |
| read | runtime_only | 3 / 3 | 0 | 0 | 8 |
| read | hybrid | 2 / 3 | 0 | 0 | 2 |
| update | source_only | 2 / 3 | 0 | 0 | 6 |
| update | runtime_only | 3 / 3 | 0 | 0 | 8 |
| update | hybrid | 3 / 3 | 0 | 0 | 9 |

## Recorded outcomes

| Run | Workflow | Condition | Status | Final guidance | Held-out |
| --- | --- | --- | --- | --- | --- |
| a11da6bc27db434d83e230b1db9b782f | update | hybrid | compatibility_failed | 5/6 | not evaluated |
| 8942ec8a5d7148a8ac0318bf78f58810 | create | source_only | candidate_boot_failed | not replayed | not evaluated |
| d4be989bb01d42a09c835f9a053bc390 | read | runtime_only | provider_failed | not replayed | not evaluated |
| c733d3e9d4854ba6a58c0281b319bd8a | update | hybrid | static_review_blocked | not replayed | not evaluated |
| 47cd7dd900b248fd925c5dc468642de3 | create | hybrid | provider_failed | not replayed | not evaluated |
| 6aaa1d2992374b7695ae1aaa8fd55b32 | update | runtime_only | compatibility_failed | 2/6 | not evaluated |
| 0465611d02064e96a02a20cf530733ca | update | runtime_only | static_review_blocked | not replayed | not evaluated |
| 2e8c448a0333424fadd607ddacd52def | create | source_only | provider_failed | 1/6 | not evaluated |
| 3efc6b53b8054ece90aadbfaf621cb2c | create | hybrid | provider_failed | not replayed | not evaluated |
| 7f450e9f2a7a4d96b8a8561f5e2ef1e8 | update | source_only | compatibility_failed | 1/6 | not evaluated |
| a7bc893f65504ea380e8cf0fe0825442 | read | hybrid | provider_failed | not replayed | not evaluated |
| a0f658e45a874a91ae7a4c5610d9b067 | create | runtime_only | provider_failed | not replayed | not evaluated |
| cdaa096814ab44638fa9867898d4f1c7 | update | runtime_only | provider_failed | 0/6 | not evaluated |
| 4ef71073cdf140c7880888b9c2908249 | update | source_only | static_review_blocked | not replayed | not evaluated |
| 9d352266b60c43fd8cc9d16a48d72445 | read | runtime_only | compatibility_failed | 3/6 | not evaluated |
| e75bf0355757496393602bd5348f000f | read | runtime_only | compatibility_failed | 0/6 | not evaluated |
| b19af9a51ade461e9e189cf920733afb | create | runtime_only | compatibility_failed | 4/6 | not evaluated |
| e0c81a30cfe44f898dba63c28453669e | create | hybrid | provider_failed | not replayed | not evaluated |
| b8ad3a31b6994ffeb1aa676fd63b7262 | update | hybrid | compatibility_failed | 3/6 | not evaluated |
| 4b155660663b4b10aa09f59c35448d56 | create | runtime_only | provider_failed | 1/6 | not evaluated |
| 88a87d3dccd941f39c0683fd5d33ebff | read | hybrid | provider_failed | not replayed | not evaluated |
| f1e6e9807497417f9dfbfdbec8b88a00 | read | source_only | provider_paused | not replayed | not evaluated |
| 4b3e42a241ed4ef78a6c8045da0ec49f | read | source_only | provider_paused | not replayed | not evaluated |

[Audited source report](report-023.json); [trial CSV](trials-023.csv).

A boot/static rejection with no replay is not labelled 0/6. Held-out failures remain final; no hidden mismatch payload is exported here.
