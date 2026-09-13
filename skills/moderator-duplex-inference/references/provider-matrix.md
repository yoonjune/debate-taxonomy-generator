# Provider matrix

| provider | canonical status | execution backend | concurrency | authorization | normalized model audio |
|---|---|---|---:|---|---|
| GPT-Live | canonical/default | pinned `run_session` from the frozen gap-only adapter | 1 | `--billing-confirmed paid-authorized` | `model_timeline.wav` |
| Gemini Live | comparison adapter | existing Gemini `run_session` | 1–3 | `--billing-confirmed free` or `paid-authorized` | `model_timeline.wav` |
| Moshi/PersonaPlex | comparison adapter | existing chronological GPU runner | 1 | `--gpu-confirmed` | `output.wav` |

The shared layer standardizes selection, hashes, collision policy, authorization, stopping behavior,
and artifact pointers. It does not erase provider differences:

- GPT-Live is pinned to the current registered-gap-only, 80 ms exact-zero transport profile.
- Gemini has provider-native completion/interruption events and may use a different controller. Record
  the exact plan/profile instead of labeling it GPT-equivalent.
- Moshi/PersonaPlex is a local frame-synchronous model path. It does not use an API playback queue or
  the same start-cue/session lifecycle unless a future adapter explicitly implements and validates it.

Cross-provider score comparisons are valid only when input cases, prompt content, removed moderator
turns, source-clock deadlines, and evaluation contract are held fixed. Transport differences must be
reported as a limitation, not hidden by the normalized index.

Invoke the common runner with the Python environment that already supports the selected native
adapter. GPT-Live and Gemini need their API dependencies and environment-provided key; Moshi needs
the pinned Moshi/PersonaPlex environment, model weights, `moderator_bench` import path, and CUDA GPU.
The skill does not install dependencies, download weights, or read secret files during dry-run.
