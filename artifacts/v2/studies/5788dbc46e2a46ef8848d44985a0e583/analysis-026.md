# Study analysis at 26/27 trials

| Condition | Recorded / planned | Guidance passes | Held-out evaluated | Workflow passes | HTTP requests | Unknown token usage |
| --- | --- | --- | --- | --- | --- | --- |
| source_only | 8/9 | 0 | 0 | 0 | 19 | 5 |
| runtime_only | 9/9 | 0 | 0 | 0 | 24 | 4 |
| hybrid | 9/9 | 0 | 0 | 0 | 18 | 6 |

- Descriptive analysis of one repository and three selected workflows.
- Recorded-trial denominators include provider, static and boot failures; pending trials are excluded. This measures observed end-to-end yield.
- Repeated trials share code, fixtures and provider conditions. Nominal Wilson intervals assume independent binomial trials and do not establish generalization or a significant difference between conditions.
- Reported tokens omit unknown usage. Latencies cover only recorded parsed outputs and exclude pacing, failed HTTP requests, container work and total wall-clock time.
- Repair pairs require an initial six-case replay and a later six-case replay. Attempts without replay are excluded from paired counts.
- The last replay may precede a terminal static/provider failure. Its partial score is not a terminal guidance pass or a held-out result.
- Incomplete study results do not establish evidence-condition superiority.

[Full descriptive analysis](analysis-026.json)
