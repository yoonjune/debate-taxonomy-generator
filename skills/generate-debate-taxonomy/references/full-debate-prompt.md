# Full-debate generation prompt

Generate one English three-speaker debate from a frozen assignment and variation card. Read
`taxonomy.md`, `generation-rules.md`, and `full-debate-contract.json` first. Return one JSON object and no
Markdown.

## Debate shape

Use only `MOD`, `PRO`, and `CON`. Keep the moderator neutral and mostly silent.

1. Phase 1: MOD introduces the motion in 6–15 seconds. PRO and CON give 24–38 second openings in that order.
2. Phase 2: the first turn is MOD with only `A3-1`; the debaters then address each other directly. MOD speaks
   only for assigned taxonomy events.
3. Phase 3: the first turn is MOD with only `A3-2`; MOD calls PRO first. PRO and CON give 24–38 second closings.

Short debates must total 210–225 seconds with 65–80 seconds in Phase 2. Long debates must total 300–330
seconds with 150–180 seconds in Phase 2. Include `A3-1`, `A3-2`, and one to three additional taxonomy codes.

There is no audience speaker and there are no audience questions. Do not introduce unverifiable precise
statistics, named studies, or extra people. Make both sides substantive and comparably strong.

## Taxonomy realization

- `A1`: a floor holder continues past an explicit deadline; MOD barges in to stop them, without calling the
  opponent.
- `A2-1`: the same overrun topology as A1, but MOD stops the speaker and explicitly hands the floor to the
  opponent, who speaks next.
- `A2-2`: a speaker finishes within the deadline; after a non-overlapping handoff, MOD calls the opponent.
- `A3-1`: opens direct debate after both opening statements.
- `A3-2`: stops direct debate and starts closings with PRO first.
- `A4`: while 8–12 seconds remain in the current floor, MOD overlays a warning of at most 10 words; the same
  floor holder continues afterward.
- `A5`: one debater interrupts the other with at most 12 words and positive overlap; MOD promptly restores the
  original floor.
- `B1`: a debater genuinely drifts away from the motion; MOD briefly redirects the debate.
- `B2`: the same debater states two explicit, logically incompatible claims before MOD accurately contrasts
  them. A qualification or narrower scope is not a contradiction.

Do not combine taxonomy events in one MOD turn. Every target taxonomy occurs exactly once on a MOD turn and
has exactly one event row. For A1, A2-1, and A4, encode the required timing/overlap in turns rather than only
describing it in `realization_note`. B1 and B2 always require transcript-only semantic review.

## Timing representation

Every turn has `gap_after_sec`, `overlap_sec`, and `overlap_with`. Use 0.2–0.8 second ordinary gaps and up to
1.2 seconds at phase boundaries. Set positive overlap only when the taxonomy topology requires it. Do not
invent `start_sec`, `end_sec`, or `predicted_duration_sec`; `validate_full_debate.py` estimates speech time
from the selected voice's word-length band.

## Output shape

```json
{
  "sample_id": "...",
  "contract_version": "0.1",
  "assignment_pair_id": "...",
  "duration_profile": "short",
  "motion": "...",
  "participants": {
    "MOD": {"name": "...", "voice_id": "MSP-PODCAST_0537_440"},
    "PRO": {"name": "...", "voice_id": "MSP-PODCAST_0177_72"},
    "CON": {"name": "...", "voice_id": "MSP-PODCAST_0941_297"}
  },
  "target_taxonomies": ["A3-1", "A5", "A3-2"],
  "variation": {},
  "turns": [
    {
      "turn_id": "p1_t001",
      "phase": 1,
      "speaker": "MOD",
      "text": "...",
      "taxonomy": [],
      "gap_after_sec": 0.5,
      "overlap_sec": 0.0,
      "overlap_with": null
    }
  ],
  "events": [
    {
      "taxonomy": "A5",
      "moderator_turn_id": "p2_t012",
      "trigger_turn_ids": ["p2_t010", "p2_t011"],
      "realization_note": "The second trigger interrupts the first."
    }
  ]
}
```

Before returning JSON, check phase order, exact speaker set, event links, target coverage, PRO-first closing,
participant balance, moderator brevity, and absence of audience language. The automatic full-debate validator
checks structure, voice-WPM duration, A3 phase boundaries, A5 overlap, and B2 same-speaker linkage. It does
not fully prove the semantic validity of A1, A2-1, A2-2, A4, B1, or B2; apply `taxonomy.md` manually as well.
