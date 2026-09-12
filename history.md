# Moderator benchmark — research history (draft for ICASSP paper)

Every number traces to a file under `debate/_meta/` or a memory note. "(TBD)" = not in the sources.

## 1. Problem & setting

- **Task.** A full-duplex speech model takes the moderator (MOD) seat in a three-person Oxford-style debate (MOD, PRO, CON). Debater audio is static; only the MOD channel is free. The model decides *when* to speak and *what* to say.
- **"Moderator" here** = format-and-time referee: floor allocation, time control, two content moves (off-motion redirect, self-contradiction). Arguing the merits, taking a side, or declaring a winner is a failure (the "substantive participant" negative class of SCOTUS chairs; `MODERATOR_EXTRACTION_MAP.md`).
- **Format (fixed; `gen2/DEBATE_SPEC.txt`).** Phase 1 openings: PRO 30 s, CON 30 s, no interruptions. Phase 2 crossfire: direct exchange, fixed at 150 s (2:30), announced by MOD together with its start point ("from the moment I stop talking"). Phase 3 closings: PRO 30 s, CON 30 s. Ten-second cue at 20 s of every 30-s speech; hard cut at 30 s. A debate runs about five minutes.
- **Why synthetic.** Without a fixed rule set no intervention can be judged right or wrong (`RULES_AND_WHY.md`, rule 6). Real corpora lack per-speaker channels, have audiences and panels, research-only licences, patchy audio (§2). **Key principle:** MOD lines are not written by the LLM; they are anonymised utterances of real moderators (a seed bank, plus a few synthetic lines for the crossfire cue). The LLM fills the debaters' slots only.

## 2. Real-debate corpora surveyed

- 55 candidate English datasets ranked on moderator presence, audio, transcript, format, download, licence (`_ranking_table.md`). Grade S (audio + moderator): N11 US Election 2020 (CC0), B3 M-Arg, B2 US-ElecDeb60To16, G3 Oyez/SCOTUS. Best behaviour labels: A2 WHoW (text only). Excluded: moderators removed (B4, B7), no chair, ASR-only, non-English.
- **Used for seeds: four moderated policy-debate corpora** — IQ2 (108 debates, 26,562 utterances, 10,246 mod turns, explicit `mod` role), OpenToDebate (208 events), Doha (66), Munk (13). After dropping interviews/special events: **366 debates, 31,264 moderator windows** (mod turn ± 4 turns; OTD 12,748 / IQ2 10,192 / Doha 8,009 / Munk 315).
- **Audio caveat.** IQ2 podcast feeds are edits: ~45 % of transcript words, ~60 % of turns dropped, host lines 0 %; only 15 of 94 paired audios align fully (coverage 0.80–0.96) (memory `iq2-audio-coverage`). Real audio was therefore unusable as the test signal.

## 3. Moderator-action taxonomy

- **Inputs.** Hand taxonomies: IQ2 21 moves (2,050-turn sample; bare-name hand-off 16.5 %); 7+1 action space on PMQs+SCOTUS (1,878 turns; G = chair debating the merits = negative class). LLM labelling of 10,192 IQ2 mod utterances (`llm_label/output/`): deductive 5x2 scheme (turn allocation 46.4 %, follow-up/summary 26.0 %, structure 19.0 %, time 5.2 %, civility/redirect 2.2 %); k-means K=25 over 6,087 free-text action labels (call next speaker 21.7 %, press for direct answer 9.9 %, interrupt to manage flow 6.7 %, enforce time limit 4.4 %). *Caution:* the 5x2 letters (A1 "opening framing") are not the final codes.
- **Final 9 codes** (A = time & floor, B = content) were selected by hand from these analyses as the moves that are rule-checkable and realisable with three speakers; audience Q&A, voting, humour and substantive probing were dropped. A1 and A2-1 are both the 30-second cut; the format decides which one applies (first speaker of a round → hand over; last speaker → nobody to hand to).

| code | definition | phase | status |
|---|---|---|---|
| A1 | over-time speaker cut off; nobody to hand to (last speaker of a round) | 1, 3 | selective |
| A2-1 | over-time speaker cut off, floor handed to the other side | 1, 3 | selective |
| A2-2 | speech ended in time; hand over | 1, 3 | mandatory |
| A3-1 | close openings, open crossfire, state its length and start point | 1→2 | mandatory |
| A3-2 | cut into crossfire at 2:30, open closings, PRO first | 2→3 | mandatory |
| A4 | "ten seconds" cue overlaid at 20 s of a speech (and at 2:20 of the crossfire); speaker continues | all | mandatory |
| A5 | block an out-of-turn interrupter, return the floor | 1, 3 | selective |
| B1 | pull a speaker who drifted off the motion back | 2 | selective |
| B2 | point out a contradiction with the speaker's own earlier claim; no verdict | 2 | selective |

- **Dependencies**: A1/A2-1 follow a ten-second cue at 20 s; A3-1↔A3-2 paired; A5 needs an out-of-turn interruption; B1 a drifting turn; B2 an absolute rule stated earlier by the same speaker. Exactly one of A1/A2-1/A2-2 ends a speech; A5 never in crossfire; B1/B2 only in crossfire. One MOD line = one job.
- **Corpus labelling** (Qwen3.5-122B-A10B-FP8, JSON-constrained, 31,264 windows, 0 parse errors): no 47.1 %, A2-2 13.9, A2-1 13.5, B1 10.0, A5 6.7, A3-1 2.6, A4 1.7, A3-2 1.6, B2 2.2 (two labelling variants), A1 0.7. Coded share: IQ2 62.6 %, Munk 60, Doha 48.4, OTD 47.4.

## 4. Seed bank

- **Candidates.** Two label runs, only agreeing labels kept (6,889); up to 300 per code, A1/A3-1 phrase-mined (227, 150); LLM rewrite replaces names/motion with `[PRO] [CON] [MOTION] [NAME]` tags → **2,424 candidates** (`gen/seed_package/README.ko.md`).
- **Review.** Three reviewers, pass/fail web app with ±6-turn context, target 30 passes per code (memory `seed-review-server`). 300 verdicts so far; passes A1 30, A5 30, B1 30, B2 20, A2-1 13, A4 4, A3-1 1, A3-2 1 (`review_app/verdicts.db`; A3-x/A4 incomplete).
- **gen2 bank** (`assets/seedbank.json`, 3,320): A2-2 2,317, A1 236, A5 222, A3-2 148, A3-1 129, B1 98, A2-1 85, A4 61, B2 24 (5 + 19 review-pass frames with `[CLAIM_A]/[CLAIM_B]`). LLM gate (`filter_seeds.py`: wrong code, needs outside context, audience/vote/panel, fragment, time ≠ ten seconds, two jobs; A5 must name who is stopped) + scene extraction → **627 scene seeds**: A3-2 148, A3-1 115, A2-2 99, A5 93, A1 45, A4 38, B1 37, A2-1 28, B2 24 (IQ2 247, OTD 227, Doha 124, Munk 9, SYN 20). Seeds mirror PRO↔CON with side words flipped; seeds with `[NAME]/[PLACE]/[ORG]/[EVENT]` unused.
- An earlier v9 pipeline (`_meta/gen`: 531 trigger+reply seeds, 496 LLM-written debates, MOD verbatim 95 %) was dropped because the LLM also wrote rules and timing.

## 5. Script generation

- Python fixes everything that must be exact: which optional codes a debate contains (balanced across the set), speech-length bands, the seed line for every MOD action, names, voices, word budgets. An LLM (`gpt-5.6-luna`, one JSON call per debate, 450-word prompt) writes only the debaters' turns and the two quoted claims for B2.
- Filtering: 22 rule checks (budgets, cut-off dashes, moderator share, no audience) and a strict LLM judge per debate (speaker/side consistency, whether every MOD line is actually earned by the turns before it, whether the planted traps stay silent-worthy). Only judged-pass debates enter the benchmark.
- The dominant generation failure is the LLM losing track of which debater speaks in crossfire; putting the speaker name and side into every output key reduced side-swapped turns from about a quarter of crossfire turns to a few percent.
- Batches: 30 generated → 21 passed (v8); a second 30 with a rewritten crossfire *question* instruction → 8 passed (the new wording tripled side-swapped question turns; reverted), plus 3 of 5 single-turn repairs → 11. Then 100 with gpt-5.6-luna → 48 passed, and 100 with gpt-5.6-terra → 64 passed (per-turn side-swap rate 6.3% → 3.1%); the 112 form `data_sample_112/`. From the 32 the 30 with the most even optional-code counts form `data_sample_30/`: A1 17 · A2-1 16 · A5 17 · B1 16 · B2 16 (28 as generated, 2 with one repaired turn).
- Judge variance: re-judging 6 accepted debates with a fresh judge passed 4; the two rejections were borderline B2 pairs. Pass/fail on a single debate is noisy; the set-level counts are what we report.

## 6. Audio

- Each turn is synthesised separately (OmniVoice, voice cloning from NaturalVoices/MSP-Podcast references; 24 kHz), trimmed with a forced aligner, and placed on a timeline. The mixer enforces the clock: ten-second cue at 20 s, cut at 30.5 s, crossfire cue at 2:20 and cut at 2:30 (declared − realised = 0.00 s), interruption blocked 1.5 s after it starts; the interrupted speaker then resumes.
- Per-turn files are kept, so the debater channel for the model is built from PRO/CON turns only.
- **Speech-end marker.** Every opening or closing statement that finishes inside its thirty seconds ends with `That's all, thank you.`, synthesised in that speaker's own cloned voice and concatenated onto the turn with a 0.30 s breath. Statements the moderator cut for time do not get it — they were stopped mid-sentence. 62 voices were synthesised (two seeds each) and reused across the 320 places; the speaker-similarity gate was not applied to these clips, because a four-word utterance is too short for a stable ECAPA embedding (median cosine 0.58 against the speaker's own reference, versus ≥ 0.60 for the full-length turns). Appending the marker moves the end of the statement, so the A2-2 and A3-1 deadlines move with it; the timeline, the probe windows, the mixes and the transcripts were all rebuilt from the shifted times, and the realised crossfire length stays at exactly 150.0 s. A later pass that stretched the cut codes so the speaker stayed audible past the end of their window was tried and reverted; the mix cuts each speaker exactly where the reference moderator cut them.
- Realised set: 112 debates (48 luna + 64 terra), 3,514 turns after dropping surplus crossfire turns, 4.4–5.5 min each (median 5.0), 77 cloned voices from Sidon-restored references; declared − realised crossfire length = 0.00 s in all 112. Every turn passed a quality gate: speaker similarity ≥ 0.60 (ECAPA-TDNN) and WER ≤ 0.10 (Whisper large-v3 + jiwer), up to three seeds; short lines (≤ 5 words) use WER only. 98% of long turns passed on the first try; all 3,691 synthesised turns were trimmed by forced alignment. The OmniVoice prompt was reordered (target before reference audio), which removed the onset artefact that earlier batches needed trimming for.

## 7. Evaluation protocol (final)

- **Free run.** The debater audio (all PRO/CON turns at their recorded times) plays from start to end; the model's own channel is open for the whole debate — nothing is forced into it and nothing is muted. Every model utterance is logged (onset time + text). The reference timeline (`probes.jsonl`) defines the triggers; the crossfire clock starts where the model's own opening utterance ended (reference end as fallback).
- **Input during a window.** The debater audio is never cut, so the window end is always audible. Clock codes: the speaker keeps talking through the A4 window (the cue is overlaid, not in the input), fades at +1.3 s for A1/A2-1 and +0.8 s for A3-2; the A5 interrupter keeps talking to at least +2.3 s. Turn-end codes (A2-2, A3-1, B1, B2): the window is the silence where the reference moderator spoke; the next debater turn starts 1.4–16 s later. Each probe carries `speech_until_sec`, `next_debater_start_sec`, `hears_in_window`.
- **Timing** per trigger (first non-back-channel onset in [deadline−5, latest+3]): PREMATURE / ON_TIME / LATE / MISSED. Windows: A4 speaker-start+20 ±2 s; A4 crossfire start+140 ±2; A3-2 start+150 ±2; A1 and A2-1 speaker-start+30 [0, +2] (the 30 s are guaranteed); A2-2 and A3-1 [speech end, +2]; A5 [interruption start, +2]; B1 and B2 [turn end, +2].
- **Content** is judged per criterion by an LLM from the utterance text, and the score is met/total, so a two-criterion code can score 0.5 and the scorer records which criterion was missing. One criterion: A4 says "ten seconds"; A2-2 hands over (name / other side / next); A3-2 moves on to the closing round; A1 stops the speaker for time; A5 restrains the interrupter; B1 steers back to the motion. Two criteria (half credit for one): A3-1 moves on to the next round *and* states the length; A2-1 stops the speaker *and* hands over; B2 points out the self-contradiction *and* asks the speaker to reconcile it. The judge never sees our code letters — it names the action in plain words from a fixed list and the mapping back to a code is applied afterwards; it is not shown the reference moderator line either. Joint = ON_TIME × score. Filler-only utterances (mm-hm, yeah, okay) or utterances under 0.4 s with at most one word are back-channels and never attributed; one-word moderator lines such as "Time." count.
- **Non-trigger speech.** No separate negative probes. Every utterance that belongs to no trigger window is logged and judged against the system prompt: `backchannel` / `acceptable` / `awkward` / `violation` (a duty in the prompt is broken — stopping a speaker before time, policing crossfire interruptions, taking a side, declaring a winner, redirecting a speaker who was on the motion — or the utterance would derail the debate). Planted traps (a digression the speaker corrects, two compatible claims, a crossfire interruption) are kept as region labels for this analysis. The format announcement at the start and the closing line are expected but not scored.
- **Reporting** per code: timing distribution, onset−deadline median/IQR, content pass, joint rate, predicted-label confusion; per debate: non-trigger utterance count and verdicts. Baselines: always silent; speak at every trigger deadline; speak whenever a debater stops (the static audio keeps the pauses where the reference moderator spoke, so this baseline shows how much of the timing task the pauses give away). System prompt: 295 words, one sentence per scored behaviour. Target models: PersonaPlex base, RL-Seamless (TBD).
- The probe-replay mode (reference moderator teacher-forced up to a release point, then one trigger freed) is kept as a secondary tool for clean per-code timing.

## 8. Numbers at a glance

| item | value |
|---|---|
| Corpora behind the seeds | 4 (IQ2, Open to Debate, Doha, Munk); 366 debates; 31,264 moderator windows labelled |
| Seed candidates → reviewed → usable scene seeds | 2,424 → 300 verdicts → 627 |
| Benchmark set | 251 debates, 2,383 triggers (A4 605 · A4 crossfire 251 · A2-2 378 · A3-1 251 · A3-2 251 · B2 139 · B1 132 · A1 131 · A2-1 124 · A5 121) |
| Per debate | 6–7 distinct codes, 8–10 scored MOD lines, 4.6–5.3 min of audio |
| Model scores | (TBD) |

## 9. Open issues / limitations

- In the free run the debater audio keeps the pauses where the reference moderator spoke, so a hand-off point is audible as a gap; this is inherent to static playback and is realistic (debaters wait), but it is a cue the model can exploit.
- A4 in the crossfire is the only long clock (140 s from the opening line); in a free run the model must also have opened the crossfire itself to know the start point — otherwise it can only infer it from the debaters.
- Both debaters share one channel; A5 and B2 require telling the voices apart.
- Script filtering and content judging rely on LLM judges.
- Real chairs often cut without a prior ten-second cue, unlike our rule; the seed review is incomplete for A3-1/A3-2/A4.
- MOD lines are human but recontextualised; debater content is synthetic; no audience. Voices are cloned TTS (OmniVoice), so prosody is flatter than real debate speech.
