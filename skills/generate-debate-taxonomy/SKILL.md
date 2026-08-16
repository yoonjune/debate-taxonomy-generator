---
name: generate-debate-taxonomy
description: Generate, diversify, repair, validate, and render three-speaker debate transcript samples for moderator taxonomy codes A1, A2-1, A2-2, A3-1, A3-2, A4, A5, B1, and B2. Use when the user asks in Korean or English to "make A3-1", "create an A4 example", generate varied short or long debates containing named taxonomy events, explain how a taxonomy should be realized, plan a reproducible variation batch, or automatically check taxonomy timing, overlap, trigger grounding, diversity, round order, and Korean translation.
---

# Generate Debate Taxonomy

Generate taxonomy evidence, not an isolated moderator sentence. Always include the observable trigger,
the MOD action, and enough aftermath to show whether the action worked.

## Interpret the request

- Default to `event-window` when the user names taxonomy only: `A4 만들어줘`.
- Use `full-debate` when the user asks for a short/long debate or complete transcript.
- Default to English transcript plus Korean reference translation.
- In `full-debate`, add required A3-1 and A3-2 automatically and keep total taxonomy count at 3–5.
- Ask only when a missing choice would materially change the result. Otherwise choose a usable motion,
  three participant names, and a duration profile and record the choices.

Read [references/taxonomy.md](references/taxonomy.md) completely for every generation request. Read
[references/generation-rules.md](references/generation-rules.md) for output structure, phase, timing,
source, and translation rules. Read [references/variation.md](references/variation.md) before choosing a
motion, trigger, roles, moderator wording, or timing. Read [references/loop-validation.md](references/loop-validation.md)
before repairing or validating a generated sample.

## Generate

1. Create and freeze a variation card. For a batch, allocate all cards before generating any transcript:

```bash
python3 skills/generate-debate-taxonomy/scripts/plan_variations.py \
  --seed <recorded-seed> A1 A2-1 A2-2 A3-1 A3-2 A4 A5 B1 B2
```

2. Freeze an assignment: mode, motion, participants, target taxonomy, duration, source locators, and the
   variation card. Preserve the card in the output as `variation`.
3. Design trigger turns before writing the moderator action.
4. For `event-window`, generate `sample.json` using the machine contract at
   `references/contract.json`. Run:

```bash
python3 skills/generate-debate-taxonomy/scripts/validate_sample.py sample.json
```

5. For `full-debate`, read [references/full-debate.md](references/full-debate.md) and use the bundled
   voice-WPM contract, prompt, and validator. Do not invent transcript timestamps or validate a full debate
   with `validate_sample.py`.
6. Apply the bounded repair loop from `references/loop-validation.md`.
7. Render a human-readable bilingual artifact. For `event-window`, run:

```bash
python3 skills/generate-debate-taxonomy/scripts/render_sample.py sample.json > sample.md
```

   For `full-debate`, use `scripts/render_full_debate.py` as specified in
   `references/full-debate.md`.

8. Report automatic checks separately from semantic or human judgment. Never call automatic validation
   human validation or benchmark correctness.

## Preserve constraints during repair

Do not change requested taxonomy, motion, mode, duration profile, participant roles, or acceptance thresholds
to make validation pass. Repair only the failing trigger, action, timing, linkage, balance, or translation.
Preserve failed attempts and validator errors when the user requests research artifacts or reproducibility.

## Validate the skill examples

Run all nine examples after changing taxonomy rules, contract, or validation code:

```bash
python3 skills/generate-debate-taxonomy/scripts/validate_examples.py
```

Treat B1 relevance and B2 logical incompatibility as requiring transcript-only semantic review even when
their structural automatic checks pass.

Read [references/example-catalog.md](references/example-catalog.md) when the user wants to inspect all nine
human-readable examples. Read `references/example-validation.json` when reporting the latest regression result.
Read [references/forward-test-report.md](references/forward-test-report.md) when reporting whether natural
requests and the bounded repair loop were tested end to end.
Read `references/variation-validation.json` when reporting planner regression results.
