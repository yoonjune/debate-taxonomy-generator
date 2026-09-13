# Campaign contract

`run_campaign.py` accepts one JSON campaign. Relative paths resolve from `--workspace-root`, not
from the campaign file.

## Common fields

- `schema_version`: exactly `moderator-duplex-inference/v1`
- `campaign_id`: stable non-empty identifier
- `provider`: `gpt-live`, `gemini`, or `moshi`; omitted means `gpt-live`
- `adapter.module_path`: existing provider implementation
- `adapter.module_sha256`: required immutable source hash
- `adapter.profile`: named semantic/runtime profile
- `jobs`: non-empty list with unique `job_id`
- `execution.no_retry`: must be `true`
- `execution.skip_complete`: must be `true`
- `execution.concurrency`: GPT-Live and Moshi require 1; Gemini permits 1–3
- `index_path`: optional normalized index destination

For GPT-Live and Gemini, each job contains `plan_path` and `plan_sha256`. The provider plan owns
case input paths, source hashes, prompts, gap manifests, and unused output directories.

For Moshi, each job contains `plan_path` for a small JSON object:

```json
{
  "schema_version": "moderator-duplex-moshi/v1",
  "prepared_dir": "reports/prepared",
  "output_dir": "reports/moshi-base",
  "model": "base",
  "selected_debates": ["L000", "L001"],
  "concurrency": 1,
  "path_remap": [
    {"from": "/old/remote/prepared", "to": "reports/local-prepared"}
  ]
}
```

`path_remap` is optional. Use it only when a frozen Moshi `index.json` or `input.json` contains
machine-specific absolute paths. The runner verifies remapped user audio, prompt, and voice hashes,
then creates an ephemeral resolved manifest; it never edits the frozen source manifest.

## State and retry rules

An absent output directory is `PENDING`. An output directory with
`generation.json.status == COMPLETE` is `COMPLETE_EXISTING` and may be skipped. Every other existing
output is `EXISTING_NONCOMPLETE` and blocks execution. Retrying requires a new explicit user decision
and a new output path or a documented recovery procedure; this skill never deletes or overwrites it.

Dry-run performs hashes, provider invariants, case selection, and collision checks without API/GPU
execution or result writes. `--collect-only` writes a normalized pointer index but never copies WAVs.

The bundled GPT-Live, Gemini, and Moshi example campaigns point to completed artifacts in the
current study workspace. Use them for regression dry-runs only. For a new run, copy the relevant
campaign and plan, choose unused output paths, and freeze new hashes before requesting execution.
