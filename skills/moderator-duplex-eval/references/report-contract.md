# Report input and output contract

Read this reference when evaluating a gap-gated GPT-Live report.

## Required inputs

- A run plan with `runs[]`. Each run needs `debate_id`, `output_dir`,
  `conditional_gap_file`, `conditional_gap_sha256`, `input_dir`, and
  `source_audio_sha256`.
- A review scaffold with `runs[]`. Each run needs `clock_spans`, `model_turns`,
  `input_turns`, and audio file links. Model times are session-clock seconds.
- The benchmark root containing `probes.jsonl`, `debates.jsonl`, and
  `audio/mix/<debate_id>.json`.
- Each run's `generation.json`, `input_sends.jsonl`, and session-aligned `input.wav`.

Paths in a plan are resolved relative to the explicitly supplied workspace root. Never infer a
different source checkout just because a file with the same debate ID exists elsewhere.

## Primary GT

The primary row is one unique moderator utterance ID listed in
`conditional_gap_file:gaps[].mod_turn_ids`. Join it to:

1. `audio/mix/<id>.json:turns[].i` for the realized moderator utterance and interval;
2. `probes.jsonl:before_turn` for the EVAL_SETTING timing trigger;
3. `debates.jsonl:turns[].i` for phase and speaker metadata.

Fail the whole debate closed when an ID is missing, duplicated, is not a MOD turn, has no unique
probe, or when the registered gap is not exact-zero in the frozen source WAV. Do not repair the
denominator manually. Gap count and runtime skip count are separate diagnostics.

One registered gap can contain more than one moderator utterance. This is why `len(gaps)` is not
the primary denominator. Overlapping EVAL_SETTING windows may attribute the same model utterance
to more than one primary GT row.

## Deterministic outputs

The first `evaluate_report.py` pass, run without `--anchor-decisions`, writes an `anchor`-stage
`review_packet.json` containing only blinded A3-1 candidates. A4xf/A3-2 rows remain explicitly
`ANCHOR_PENDING`; they are not timed or semantically reviewed in that pass. After the A3-1 review,
`derive_anchor_decisions.py` records whether each debate uses the model A3-1 end or the reference
`xf_open_sec` fallback. The full pass requires that file.

The full `evaluate_report.py` pass writes:

- `denominator_contract.json`: provenance, validation, and case-wise primary GT counts;
- `timing.json`: primary GT timing rows and deterministic aggregate;
- `barge_in_candidates.json`: waveform-based onset overlap and stale-review candidates;
- `mechanical.json`: reproducible transport assertions exposed by the run logs;
- `review_packet.json`: blinded content/non-trigger/stale items for a fresh reviewer;
- `review_key.json`: the mapping that must not be shown to the content reviewer;
- `manifest.json`: input hashes and scorer configuration.

For a reference fallback, map `xf_open_sec + 140 s` or `xf_open_sec + 150 s` through the complete
piecewise clock. For a valid model anchor, add the offset to the model A3-1 utterance's session end.
The two operations are intentionally different when registered gaps were skipped.

The deterministic stage never invents content scores. It writes `UNKNOWN` until a review is
merged.

## Semantic review output

Give only `review_packet.json` and the exact system instruction embedded in it to a fresh Codex
session. The packet embeds this output contract so the reviewer must not rename `items` to
`reviews` or expand `met` into criterion objects. A review file has this shape:

```json
{
  "reviewer": {"model": "gpt-5.6-luna", "fresh_session": true},
  "items": [
    {
      "review_id": "opaque id from packet",
      "met": [true, false],
      "why": ["criterion one reason", "criterion two reason"],
      "action": "one action copied from the supplied list"
    },
    {
      "review_id": "opaque non-trigger id",
      "verdict": "acceptable",
      "violated_duty": null,
      "why": "one sentence"
    }
  ]
}
```

Do not show `review_key.json`, taxonomy codes, reference moderator text, or timing class to the
content reviewer. Missing or malformed judgments remain `UNKNOWN`.

`apply_semantic_review.py` validates this file and writes `final_evaluation.json`. Report the
result as provisional unless an independent human validity protocol was actually completed.
Concrete row-level errors found during root review may be replaced only through a separately saved,
fresh, blinded subset review passed with `--adjudications`; the final JSON retains its provenance
and overridden IDs.
