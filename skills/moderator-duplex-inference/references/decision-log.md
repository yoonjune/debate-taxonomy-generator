# Decision log

- 2026-09-13: Created a shared campaign control plane for GPT-Live, Gemini Live, and
  Moshi/PersonaPlex. GPT-Live is the canonical default.
- 2026-09-13: Frozen `gpt-live-gap-only-1000ms-v1` to the adapter SHA and runtime invariants used by
  the completed five-case run. Provider portability must not change those semantics.
- 2026-09-13: Standardized dry-run, exact source/plan hash checks, no-overwrite/no-retry behavior,
  explicit API/GPU authorization, queue stopping, and a provider-neutral pointer index.
- 2026-09-13: Normalization intentionally does not claim identical provider boundary semantics or
  identical stochastic audio output.

## 2026-09-13 — silence_cap_sec 2.0, and a new profile name

A registered gap where the model stays silent used to play out at its full reference
length. Measured over the 251-debate set that is a median 13.1 s of dead air at A3-1,
8.6 s at B2, 6.3 s at B1 and 2.7 s at A2-2 — 178 minutes across the set. A moderator
that says nothing should leave a beat, not a hole.

The gap is now capped at **2.0 s** when no model audio arrives. 2.0 s is not arbitrary:
it is the end of the ON_TIME window, so a model that answers in time is never cut off,
and a model that answers late now talks over the next debater — which is what happens in
a real debate. Once the model does speak, the existing rule is unchanged: pause, resume
1.0 s after its audio drains, drop the remainder.

Overlay codes are unaffected. A4, A4xf and A5 have no exactly-zero interval to register,
so nothing is paused there and nothing is capped.

This changes frozen transport behaviour, so the profile is renamed
`gpt-live-gap-only-1000ms-cap2s-v1` rather than edited in place. The adapter has to
implement the cap and be re-pinned; `canonical_adapter_sha256` is TBD until it is.
Numbers produced under `gpt-live-gap-only-1000ms-v1` are not comparable to numbers
produced under this profile.
