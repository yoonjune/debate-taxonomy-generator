---
name: moderator-duplex-inference
description: Run and audit reproducible batch inference campaigns for the moderator duplex benchmark across GPT-Live, Gemini Live, and Moshi/PersonaPlex. Use when preparing, dry-running, executing, resuming, or comparing provider runs; GPT-Live is the canonical default and its frozen transport semantics must not be weakened for portability.
---

# Moderator Duplex Inference

Use the manifest-driven runner in `scripts/run_campaign.py`. It provides one control plane for
provider-specific session implementations; it does not pretend that different providers expose the
same audio boundary or interruption primitives.

## Required workflow

1. Read `references/campaign-contract.md` before creating or changing a campaign.
2. If the provider is omitted, use `gpt-live`.
3. For GPT-Live, read `references/gpt-live-canonical.json` and require every frozen invariant and the
   pinned bundled adapter SHA to pass. Invoke that adapter's `run_session` unchanged.
4. For Gemini or Moshi/PersonaPlex, read `references/provider-matrix.md`. Preserve provider-native
   differences in the campaign and normalized index rather than relaxing GPT-Live behavior.
5. Run a dry-run before any inference. Dry-run must be network-free and must not create output.
6. API execution requires the user's explicit billing authorization in the current turn and
   `--billing-confirmed`; local Moshi execution requires explicit GPU authorization and
   `--gpu-confirmed`.
7. Never overwrite an output directory. Skip only an existing `COMPLETE` run. Stop the remaining
   queue after an error and never retry automatically.
8. After execution, collect the provider-neutral campaign index. Evaluate it separately with
   `moderator-duplex-eval`; inference must not silently judge its own outputs.

## Independent install check

The current GPT-Live adapter is bundled under `scripts/adapters/`; it must not depend on a
repository-external `tasks/` path. From any clone or installed copy, verify the control plane,
bundled SHA, and 2-second cap logic before making a campaign:

```bash
python -m unittest discover \
  -s skills/moderator-duplex-inference/scripts \
  -p 'test_*.py'
```

For execution, create a virtual environment and install `requirements-gpt-live.txt`, copy
`references/gpt-live-campaign.template.json`, fill the plan path and SHA, and dry-run:

```bash
python skills/moderator-duplex-inference/scripts/run_campaign.py \
  --workspace-root /path/to/campaign-workspace \
  --campaign /path/to/campaign.json \
  --dry-run
```

The workspace may contain `.envs/.env`; load it in the shell before execution so
`OPENAI_API_KEY` is in the process environment. The skill never reads or copies the secret file.
Execution uses the same command with `--execute --billing-confirmed paid-authorized` after explicit
billing authorization. The old `gpt-live-five-case.example.json` is an archival v1 manifest for the
completed pre-cap run, not a runnable current-profile example.

## GPT-Live equivalence boundary

"Same" means the same session implementation and the same input/transport contract, not identical
stochastic speech bytes. The regression gate pins the bundled adapter source SHA, plan hashes, model,
endpoint, 24 kHz/80 ms transport, 1000 ms release pad, PCM peak threshold 256, exact-zero gating,
registered-gap-only skip, one start cue, concurrency one, and 15-second receive tail.

If the canonical adapter changes, create a new named profile and decision record. Never update the
old SHA in place and describe the result as the same condition.
