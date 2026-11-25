# Local model experiment artifacts

These synthetic study artifacts contain candidate code as JSON text. Review the source before evaluating it with the restricted Docker runner; never import it on the host.

- `raw_proposals/`: unchanged original model drafts.
- `raw_comparison.json`: source-only and hybrid fail import; runtime-only is evaluated with 0/6 steps matching.
- `compatibility_repaired/`: separately labeled startup/observer repairs with original hashes and a diff manifest.
- `compatibility_comparison.json`: all repaired candidates complete evaluation, with zero complete steps matching for each.
- `compatibility_static_review.json`: heuristic review findings, not functional verification.

See [the experiment notes](../../docs/model-experiment.md) for results, review provenance, reproduction commands, and limits. Credentials are not needed to replay the saved study.
