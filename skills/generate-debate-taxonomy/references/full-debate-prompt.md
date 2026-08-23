# Full-debate generation prompt

Generate one English three-speaker debate from a frozen assignment and variation card. Read
`taxonomy.md`, `generation-rules.md`, and `full-debate-contract.json` first. Return one JSON object and no
Markdown.

## Debate shape

Use only `MOD`, `PRO`, and `CON`. Keep the moderator neutral and mostly silent.

1. Phase 1: MOD opens in 8–20 seconds. The opening must **say the rules out loud**: name the
   motion, say who takes which side, and state that each debater gets **thirty seconds** to
   open, then open crossfire, then thirty-second closings. A model that is later asked to
   moderate hears only the transcript, so a limit that is never spoken cannot be graded.
   PRO and CON then open in that order.
2. Phase 2: the first turn is MOD with only `A3-1`; the debaters then address each other directly. MOD speaks
   only for assigned taxonomy events.
3. Phase 3: the first turn is MOD with only `A3-2`; MOD calls PRO first. PRO and CON give 24–38 second closings.

Short debates must total 210–225 seconds with 65–80 seconds in Phase 2. Long debates must total 300–330
seconds with 150–180 seconds in Phase 2. Include `A3-1`, `A3-2`, and one to three additional taxonomy codes.

There is no audience speaker and there are no audience questions. Do not introduce unverifiable precise
statistics, named studies, or extra people. Make both sides substantive and comparably strong.

**Fixed timing.** A debater speech is limited to **thirty seconds** in Phase 1 and Phase 3.
A speech that passes **twenty seconds** gets a **ten-second** cue — always ten, never eight or
twelve. A speech under twenty seconds gets no cue. A speech that passes thirty seconds is cut off.

**Never swap sides.** PRO argues for the motion in every single turn and CON argues against it
in every single turn. Answering a question, conceding a point, or agreeing on a detail is not
taking the other side's position.

**Unfinished turns.** A turn that the moderator or the other debater cuts into must stop in the
middle of a sentence and end with a single hyphen, like `and the cost of that is-`. No period,
no ellipsis, no closing clause. If the speaker finishes cleanly, nothing was interrupted.

## Taxonomy realization

- `A1`: a floor holder continues past the thirty-second limit; MOD barges in to stop them, without
  calling the opponent. The same speaker must already have received the ten-second cue, the
  trigger turn must end unfinished, and no debater may speak again in that phase — otherwise it
  is `A2-1`, not `A1`.
- `A2-1`: the same overrun topology as A1 including the earlier ten-second cue and the unfinished
  trigger, but MOD stops the speaker and explicitly hands the floor to the opponent, who speaks next.
- `A2-2`: a speaker finishes within the deadline; after a non-overlapping handoff, MOD calls the opponent.
- `A3-1`: opens direct debate after both opening statements.
- `A3-2`: stops direct debate and starts closings with PRO first. The last Phase 2 turn must end
  unfinished — the moderator is cutting in, not waiting for a clean stop.
- `A4`: with **ten** seconds left in the current floor, MOD overlays a warning of at most 12 words
  that says `ten seconds`; the same floor holder continues afterward and finishes the speech.
  MOD does not take the floor and does not call the next speaker.
- `A5`: only in Phase 1 or Phase 3, where interrupting is against the rules. One debater interrupts
  the other with at most 12 words, positive overlap, and an unfinished ending; MOD promptly restores
  the original floor and names who keeps it.
- `B1`: only in Phase 2. A debater genuinely drifts away from the motion; MOD briefly redirects.
- `B2`: only in Phase 2. The same debater states two explicit, logically incompatible claims before
  MOD accurately contrasts them. A qualification or narrower scope is not a contradiction. Choose
  one of two ranges: the first claim sits in the Phase 1 opening, or a few turns earlier in Phase 2.

Do not combine taxonomy events in one MOD turn. Every target taxonomy occurs exactly once on a MOD turn and
has exactly one event row. For A1, A2-1, and A4, encode the required timing/overlap in turns rather than only
describing it in `realization_note`. B1 and B2 always require transcript-only semantic review.

## Timing representation

Every turn has `gap_after_sec`, `overlap_sec`, and `overlap_with`. Use 0.2–0.8 second ordinary gaps and up to
1.2 seconds at phase boundaries. Do not invent `start_sec`, `end_sec`, or `predicted_duration_sec`;
`validate_full_debate.py` estimates speech time from the selected voice's word-length band.

**Declare every interruption.** `A1` `A2-1` `A3-2` `A4` `A5` land on top of the turn they cut into,
so their moderator turn must carry `overlap_sec > 0` and an `overlap_with` naming that turn.
`A2-2` and `A3-1` follow a clean stop and carry no overlap. Prose alone does not create an
interruption: if the overlap is not declared, the two voices never touch in the synthesized audio.
How many seconds they overlap is decided at synthesis time from the real voice lengths — this stage
only has to record **whether** it overlaps and **what** it overlaps.

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
