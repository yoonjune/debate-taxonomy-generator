# Moderator Baseline Research Instructions

## Scope

These instructions apply to everything under `baselines/`.

The objective is to compare full-duplex moderator models under a shared,
reproducible protocol. The current ten debates in `data_sample/` are exposed
development data. Do not describe results on them as confirmatory benchmark
performance.

## Experimental contract

- Keep the dataset revision, rendered system prompt, moderator reference voice,
  audio streams, release time, decoding parameters, seed, and hardware fixed
  when comparing checkpoints.
- Treat `nvidia/personaplex-7b-v1` and
  `kyutai/personaplex-rl-seamless` as paired checkpoints of the same model
  family. Share the runtime and change only the pinned model configuration.
- Stream audio in chronological frames. Do not pass the whole waveform as a
  single turn and call it real-time inference.
- Before a probe release point, feed participant audio as the user stream and
  ground-truth moderator audio as the agent stream. After release, continue the
  participant stream and let the model generate the agent stream.
- Never mix the ground-truth target moderator utterance into the user stream.
- Release generation before the decision deadline so premature interventions
  remain observable.
- Preserve every run, including silence, crashes, late responses, and malformed
  output. Do not silently retry with different settings.

## Evaluation contract

- Score whether to speak, when speech begins, and what action was spoken as
  separate quantities.
- Temporal scoring is deterministic and uses `probes.jsonl` timestamps.
- Semantic scoring consumes an explicit judge record. Never infer a semantic
  pass from timing or from similarity to the reference wording alone.
- Aggregate paired comparisons by debate, not by pretending probes from the
  same debate are independent.
- Record model and code revisions, dependency lock, GPU, seed, prompt hash,
  input hashes, and output hashes in the run manifest.
- Same-family automated review is provisional. Human validation is required
  before freezing benchmark gold, especially for B1, B2, A5, and A3-2.

## Data discipline

- Do not edit `data_sample/` to make a model pass. Derived streams and model
  outputs belong under the configured artifact directory, which is gitignored.
- Do not select prompts, thresholds, or decoding parameters on the future test
  set.
- If a model cannot consume the full context, stop with an explicit error until
  a windowing contract is preregistered. Do not truncate silently.
- Keep upstream licenses and access requirements in the run documentation.

## Code discipline

- Model-specific adapters implement the common protocol in
  `moderator_bench.adapters.base`; evaluation code must not branch on model
  names.
- Heavy model imports are lazy so data preparation and scoring remain runnable
  without a GPU environment.
- Add or update tests for every schema, timing, release-mask, or stream-building
  change.
- Commit changes in reviewable units and explain negative results in the commit
  or accompanying documentation.
