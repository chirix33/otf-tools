# Additional domains (planned 2026-10-23)

Why: a single synthetic benchmark (CLEVRER) invites "you just found another way to solve CLEVRER" and a direct
comparison with Think Before You Simulate (WACV 2024), which also covers CLEVRER and CRAFT. Three non-physics
domains, each a different kind of process, answer that.

| Paper name | Spec | Source data | What is real | What is simulated | Question types |
|---|---|---|---|---|---|
| Physics | (existing) | CLEVRER validation | annotations | renderer only | all 4 |
| Manufacturing | [manufacturing.md](manufacturing.md) | SupplyGraph (FMCG manufacturer, Bangladesh) | daily production and sales orders per product, plant and storage assignments | stock, dispatch and backorder policy | all 4 |
| IT operations | [it_operations.md](it_operations.md) | Google cluster trace 2011 (`clusterdata-2011-2`) | job/task arrivals, priorities, resource requests, run durations, machine failures | scheduler policy on a small cluster | all 4 |
| Finance | [finance.md](finance.md) | TAT-HQA (real annual-report tables and text) | everything, including gold answers | nothing | descriptive, counterfactual |

## Rules shared by all three

1. **The benchmark is designed from the domain, not from OTF.** Question forms are the what-ifs a person in the
   domain would ask (removals *and* changed values, delays, capacities), whether or not OTF supports them today.
   Generator code must not import `otf/` or any system code.
2. **Gold comes from the rules, never from an LLM.** Manufacturing and IT: a reference simulator implements the
   policy written in the document's front matter; counterfactual gold = re-run with the one change, everything
   else (the recorded exogenous inputs) held as recorded. Finance: the dataset's own gold.
3. **Every question names its scope** (the unit a question is about), as CLEVRER questions name their video.
4. **No tuning on these domains, for any system.** Every system runs with its frozen settings (SPEC). One small
   dev document per domain exists only for pipeline smoke tests; its results are not used to choose anything.
5. **Same harness**: `questions.jsonl` (no type, no gold), `gold.jsonl`, `manifest.json`, `document.pdf`, the
   shared answer contract and scorer; finance needs a numeric scorer extension (see finance.md).
6. **Validation before any system sees a question**: reference simulator re-run is deterministic; 20 questions per
   domain hand-checked against the document; every MC question has at least one correct and one wrong choice
   in the pool overall (no constant-answer templates).
7. **Size**: about 3 test documents and ~300 questions per domain (~75 per type where the type exists), plus the
   dev document.

## Data on disk (git-ignored, `data/domains/raw/`)

| Folder | Source | License | Notes |
|---|---|---|---|
| `supplygraph/` | github.com/CIOL-SUST/SupplyGraph | **LGPL-2.1** (repo LICENSE; a third-party listing said MIT, which is wrong) | 221 days (2023-01-01 to 2023-08-09), 41 product columns, units + weight |
| `google-trace-2011/` | storage.googleapis.com/clusterdata-2011-2 (public bucket, no account needed) | **CC-BY 4.0** | so far: schema, SHA256SUM, job_events part 0, task_events part 0, machine_events (checksums verified). The 2019 trace needs BigQuery, so 2011 is used |
| `google-cluster-data/` | github.com/google/cluster-data | CC-BY 4.0 (docs) | trace documentation |
| `tat-hqa/` | github.com/NExTplusplus/TAT-HQA | **Apache-2.0** (repo) | dev: 274 contexts, 824 counterfactual + 1,644 factual questions; test answers hidden, so dev (and train) are used |

Citations required: SupplyGraph (Wasi et al., arXiv 2401.15299), Google trace (Reiss, Wilkes, Hellerstein 2011
trace documentation), TAT-HQA (Li et al., ACL 2022) and TAT-QA (Zhu et al., ACL 2021).
