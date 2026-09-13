# Decision log

- 2026-09-13: Created a shared campaign control plane for GPT-Live, Gemini Live, and
  Moshi/PersonaPlex. GPT-Live is the canonical default.
- 2026-09-13: Frozen `gpt-live-gap-only-1000ms-v1` to the adapter SHA and runtime invariants used by
  the completed five-case run. Provider portability must not change those semantics.
- 2026-09-13: Standardized dry-run, exact source/plan hash checks, no-overwrite/no-retry behavior,
  explicit API/GPU authorization, queue stopping, and a provider-neutral pointer index.
- 2026-09-13: Normalization intentionally does not claim identical provider boundary semantics or
  identical stochastic audio output.
