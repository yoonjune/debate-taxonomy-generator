---
name: moderator-duplex-eval
description: Evaluate full-duplex moderator speech runs under EVAL_SETTING.md, including removed-moderator-utterance GT extraction, deterministic timing and barge-in diagnostics, blinded semantic review packets, and provisional aggregation. Use for GPT-Live or other moderator-run reports; do not use it to select prompts from test outcomes.
---

# Moderator duplex evaluation

Use the repository-root `EVAL_SETTING.md` as the authoritative evaluation contract. Do not fall
back to another scorer or rubric. The versioned machine-readable snapshot used by the scripts is
[references/eval-contract.json](references/eval-contract.json); update and validate that snapshot
whenever `EVAL_SETTING.md` changes.

Design decisions and superseded assumptions are recorded in
[references/decision-log.md](references/decision-log.md).

This skill evaluates completed runs. It does not authorize inference, retries, judge API calls,
publishing audio, or changing frozen inputs.

## Choose the evaluation frame

For a gap-gated run whose input was built by removing registered moderator intervals, the primary
unit is one unique removed moderator utterance:

```text
conditional gap registry gaps[].mod_turn_ids
  -> realized timeline turns[].i
  -> probes.jsonl before_turn
```

Do not use a fixed number of actions per debate. Do not use `len(gaps)` or runtime skip count as the
primary denominator: one gap can contain multiple moderator utterances, and a registered gap need
not be skipped at runtime. Preserve those counts as separate diagnostics.

Read [references/report-contract.md](references/report-contract.md) before adapting a GPT-Live
report or producing semantic-review data.

## Two-pass deterministic stage

The A4xf/A3-2 clock is conditional on whether the model actually opened crossfire. Therefore run
an anchor pass before the full pass. First create the blinded A3-1-only packet:

```bash
python3 skills/moderator-duplex-eval/scripts/evaluate_report.py \
  --workspace-root /absolute/workspace \
  --report-dir /absolute/report \
  --plan /absolute/report/plan.json \
  --scaffold /absolute/report/review_scaffold.json \
  --benchmark-root /absolute/data_sample_112 \
  --out /absolute/report_anchor_stage
```

Give only `report_anchor_stage/review_packet.json` to a fresh Codex session, save its JSON review,
then derive the anchor decisions:

```bash
python3 skills/moderator-duplex-eval/scripts/derive_anchor_decisions.py \
  --deterministic-dir /absolute/report_anchor_stage \
  --reviews /absolute/anchor_reviews.json \
  --out /absolute/anchor_decisions.json
```

Run the complete deterministic pass with those decisions:

```bash
python3 skills/moderator-duplex-eval/scripts/evaluate_report.py \
  --workspace-root /absolute/workspace \
  --report-dir /absolute/report \
  --plan /absolute/report/plan.json \
  --scaffold /absolute/report/review_scaffold.json \
  --benchmark-root /absolute/data_sample_112 \
  --anchor-decisions /absolute/anchor_decisions.json \
  --out /absolute/report_corrected_v2
```

Use a new output directory. The script refuses to overwrite a non-empty directory. It must:

- verify the plan's source-WAV hash, the gap registry's raw PCM-payload hash, and the realized-timeline hash;
- require every `mod_turn_id` to join uniquely to a MOD timeline turn and a probe;
- verify every registered source gap is exact-zero PCM;
- count primary GT by unique moderator utterance ID, case by case;
- map static source deadlines through recorded piecewise clock spans;
- treat a temporal A3-1 candidate as the model anchor only when blinded review confirms that its
  round-change criterion is met; otherwise fall back to the reference `xf_open_sec` clock;
- map the full fallback deadlines `xf_open_sec + 140 s` and `xf_open_sec + 150 s` through the
  piecewise source-to-session clock (do not map `xf_open_sec` and then add session seconds);
- select the first eligible non-backchannel onset in the EVAL_SETTING search zone and assign
  `PREMATURE`, `ON_TIME`, `LATE`, or `MISSED` deterministically;
- allow one utterance to serve overlapping windows, as EVAL_SETTING permits;
- derive participant-speech intervals from the session-aligned input WAV and intersect them with
  declared participant turns before counting onset barge-ins;
- generate stale-action candidates without granting primary credit;
- expose mechanical transport assertions separately from evaluation scores;
- leave every semantic field `UNKNOWN` and write blinded review packets.

Treat the participant PCM VAD in `eval-contract.json` as an operational diagnostic, not semantic
gold. If a different threshold is needed, preregister a new contract version rather than changing
it after inspecting outcomes.

Fail the affected debate closed on a missing/duplicate join, hash mismatch, invalid clock mapping,
non-zero registered gap, missing A3-1 anchor review, or ambiguous anchor. Do not hand-edit the
denominator or force an outcome.

## Semantic stage

Give only `review_packet.json` to a fresh Codex session. Under the project policy, do not use
Claude. Keep taxonomy codes, timing classes, reference moderator lines, and `review_key.json`
hidden from the content reviewer.

The reviewer handles only what code cannot decide:

- per-criterion content correctness and half credit;
- predicted action;
- unmatched `acceptable` / `awkward` / `violation` judgments;
- whether a temporal stale candidate actually satisfies the earlier missed action.

Timing class, GT membership, waveform overlap, gate compliance, and denominators are not reviewer
choices. A model-only review is provisional and is not human gold.

After saving the reviewer JSON in the schema from `report-contract.md`, run:

```bash
python3 skills/moderator-duplex-eval/scripts/apply_semantic_review.py \
  --deterministic-dir /absolute/report_corrected_v2 \
  --reviews /absolute/reviews.json \
  --out /absolute/report_corrected_v2/final_evaluation.json
```

If root review finds a concrete row-level judge error, do not hand-edit it. Give only the disputed
items from the same blinded packet to another fresh Codex session, save that subset review, and add
one `--adjudications /absolute/subset_review.json` argument per adjudication file. The final artifact
records every overridden review ID and reviewer provenance. Do not use this mechanism to tune broad
verdict policy after seeing aggregate scores.

Missing or malformed review items remain visible as `UNKNOWN`; never infer a pass from timing or
reference-text similarity.

## Required reporting

Keep these denominators visible and separate:

- primary removed moderator utterances, by case and total;
- registered gaps;
- runtime skips;
- non-backchannel model utterances;
- barge-ins and backchannels over participant speech.

Report per code: timing distribution, onset-minus-deadline distribution, content mean, joint mean,
half-credit breakdown, and predicted-action confusion. Report per debate: primary GT count,
non-trigger utterances and verdicts, plus mechanical failures.

For §4.1, count utterances rather than chunks or overlap spans and use this disjoint precedence:

1. on-time required and correct;
2. late required and correct;
3. premature but content-correct;
4. other matched barge-in;
5. stale required action;
6. other contextually acceptable barge-in;
7. other awkward or violating barge-in.

Stale findings never rematch an utterance or change `MISSED`. Keep A4 and A4xf separate.

When a listening report is requested, use the canonical `audio-eval-timeline` UI and populate it
only from the corrected artifacts produced by this skill.

## Validation

Run the skill's unit tests and the system skill validator after changes:

```bash
python3 skills/moderator-duplex-eval/scripts/test_evaluate_report.py
python3 /path/to/skill-creator/scripts/quick_validate.py skills/moderator-duplex-eval
```

For a real pilot, also require:

- computed case counts reconcile with unique `mod_turn_ids`;
- timing rows sum to the computed primary denominator;
- every barge-in diagnostic group reconciles to the utterance-level barge-in total after review;
- mechanical checks and input hashes are explicit;
- the report states reviewer provenance and `human_gold: false` unless a real human protocol ran.
