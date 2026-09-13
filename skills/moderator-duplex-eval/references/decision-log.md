# Evaluation skill decision log

## 2026-09-13 — removed-moderator primary frame

- `EVAL_SETTING.md` is the sole authority for timing classes, content criteria, outside-window
  review, and §4.1 diagnostics. Code does not import semantic criteria from another rubric.
- For gap-gated inputs, primary GT is a unique moderator utterance referenced by
  `gaps[].mod_turn_ids`, not a fixed ten probes per debate, the number of gaps, or runtime skips.
- Static trigger deadlines are mapped into the session clock. A4xf/A3-2 use the end of the model's
  attributed A3-1 utterance directly in session time only when blinded content review confirms the
  round-change criterion. A temporally attributed but semantically unrelated utterance is not an
  opening anchor; those cases use the reference `xf_open_sec` fallback.
- Anchor selection is a mandatory two-pass procedure. In the fallback branch the complete source
  deadline (`xf_open_sec + 140 s` or `+ 150 s`) is mapped through the piecewise clock; in the model
  branch the corresponding offset is added to the model A3-1 session end.
- Participant barge-in detection uses a versioned PCM VAD and declared participant-turn support.
  It is a reproducible operational diagnostic, not human speech-activity gold.
- Deterministic code produces blinded semantic packets. A fresh Codex reviewer decides content,
  contextual acceptability, and stale correctness; model-only results remain provisional.
- The blinded packet carries its own strict output schema (`items[].met/why/action` or
  `items[].verdict/violated_duty/why`) so automatic merge never depends on an out-of-band prompt or
  manual review-file conversion.
- A root-discovered row-level judge error is corrected by a fresh blinded subset adjudication,
  never by editing the primary review. The finalizer applies explicit overrides and preserves their
  paths, reviewer metadata, and review IDs.
- Required report statistics (per-code onset median/IQR, half-credit causes, predicted-action
  counts, and per-debate non-trigger verdicts) are derived from finalized rows by code rather than
  filled into narrative reports manually.
