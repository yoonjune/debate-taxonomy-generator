# Moderator benchmark — research history (draft for ICASSP paper)

Every number traces to a file under `debate/_meta/` or a memory note. "(TBD)" = not in the sources.

## 1. Problem & setting

- **Task.** A full-duplex speech model takes the moderator (MOD) seat in a three-person Oxford-style debate (MOD, PRO, CON). Debater audio is static; only the MOD channel is free. The model decides *when* to speak and *what* to say.
- **"Moderator" here** = format-and-time referee: floor allocation, time control, two content moves (off-motion redirect, self-contradiction). Arguing the merits, taking a side, or declaring a winner is a failure (the "substantive participant" negative class of SCOTUS chairs; `MODERATOR_EXTRACTION_MAP.md`).
- **Format (fixed; `gen2/DEBATE_SPEC.txt`).** Phase 0 openings: PRO 30 s, CON 30 s, no interruptions. Phase 1 crossfire: direct exchange, fixed at 150 s (2:30), announced by MOD together with its start point ("from the moment I stop talking"); pilots used D in {150, 180, 210} s before the length was fixed. Phase 2 closings: PRO 30 s, CON 30 s. Ten-second cue at 20 s of every 30-s speech; hard cut at 30 s. Total 3:30–5:30. Text timed at 170 wpm (30 s = 85 words, 20 s = 57, 10 s = 28).
- **Why synthetic.** Without a fixed rule set no intervention can be judged right or wrong (`RULES_AND_WHY.md`, rule 6). Real corpora lack per-speaker channels, have audiences and panels, research-only licences, patchy audio (§2). **Key principle:** the LLM never writes MOD lines; they are anonymised real utterances (seeds). The LLM fills debater slots only.

## 2. Real-debate corpora surveyed

- 55 candidate English datasets ranked on moderator presence, audio, transcript, format, download, licence (`_ranking_table.md`). Grade S (audio + moderator): N11 US Election 2020 (CC0), B3 M-Arg, B2 US-ElecDeb60To16, G3 Oyez/SCOTUS. Best behaviour labels: A2 WHoW (text only). Excluded: moderators removed (B4, B7), no chair, ASR-only, non-English.
- **Used for seeds: four moderated policy-debate corpora** — IQ2 (108 debates, 26,562 utterances, 10,246 mod turns, explicit `mod` role), OpenToDebate (208 events), Doha (66), Munk (13). After dropping interviews/special events: **366 debates, 31,264 moderator windows** (mod turn ± 4 turns; OTD 12,748 / IQ2 10,192 / Doha 8,009 / Munk 315).
- **Audio caveat.** IQ2 podcast feeds are edits: ~45 % of transcript words, ~60 % of turns dropped, host lines 0 %; only 15 of 94 paired audios align fully (coverage 0.80–0.96) (memory `iq2-audio-coverage`). Real audio was therefore unusable as the test signal.

## 3. Moderator-action taxonomy

- **Inputs.** Hand taxonomies: IQ2 21 moves (2,050-turn sample; bare-name hand-off 16.5 %); 7+1 action space on PMQs+SCOTUS (1,878 turns; G = chair debating the merits = negative class). LLM labelling of 10,192 IQ2 mod utterances (`llm_label/output/`): deductive 5x2 scheme (turn allocation 46.4 %, follow-up/summary 26.0 %, structure 19.0 %, time 5.2 %, civility/redirect 2.2 %); k-means K=25 over 6,087 free-text action labels (call next speaker 21.7 %, press for direct answer 9.9 %, interrupt to manage flow 6.7 %, enforce time limit 4.4 %). *Caution:* the 5x2 letters (A1 "opening framing") are not the final codes.
- **Final 9 codes** (A = time & floor, B = content): only rule-checkable moves realisable with three speakers; audience Q&A, voting, humour, substantive probing dropped (lineage reconstructed — confirm).

| code | definition | phase | status |
|---|---|---|---|
| A1 | over-time speaker cut off; nobody to hand to (last speaker of round) | 0, 2 | selective |
| A2-1 | over-time speaker cut off, floor handed to other side | 0, 2 | selective |
| A2-2 | speech ended in time; hand over, no time talk | 0, 2 | mandatory |
| A3-1 | close openings, open crossfire, state its length | 0→1 | mandatory |
| A3-2 | cut into crossfire at 2:30, open closings, PRO first | 1→2 | mandatory |
| A4 | "ten seconds" cue overlaid at 20 s of a speech (and at 2:20 of the crossfire); speaker continues | all | mandatory |
| A5 | block out-of-turn interrupter, return the floor | 0, 2 | selective |
| B1 | pull a speaker who drifted off the motion back | 1 | selective |
| B2 | point out contradiction with the speaker's own earlier claim; no verdict | 1 | selective |

- **Dependencies** (`DEBATE_SPEC.txt` §3): A1/A2-1 require a prior A4; A3-1↔A3-2 paired; A5 needs a planted interruption; B1 a planted drift; B2 a planted claim by the same speaker. Exactly one of A1/A2-1/A2-2 ends a speech; A1 only after CON; A5 never in crossfire; B1/B2 only in crossfire. One MOD line = one job.
- **Corpus labelling** (Qwen3.5-122B-A10B-FP8, JSON-constrained, 31,264 windows, 0 parse errors): no 47.1 %, A2-2 13.9, A2-1 13.5, B1 10.0, A5 6.7, A3-1 2.6, A4 1.7, A3-2 1.6, B2-2 1.6, A1 0.7, B2-1 0.6. Coded share: IQ2 62.6 %, Munk 60, Doha 48.4, OTD 47.4.

## 4. Seed bank

- **Candidates.** Two label runs, only agreeing labels kept (6,889); up to 300 per code, A1/A3-1 phrase-mined (227, 150); LLM rewrite replaces names/motion with `[PRO] [CON] [MOTION] [NAME]` tags → **2,424 candidates** (`gen/seed_package/README.ko.md`).
- **Review.** Three reviewers, pass/fail web app with ±6-turn context, target 30 passes per code (memory `seed-review-server`). 300 verdicts so far; passes A1 30, A5 30, B1 30, B2 20, A2-1 13, A4 4, A3-1 1, A3-2 1 (`review_app/verdicts.db`; A3-x/A4 incomplete).
- **gen2 bank** (`assets/seedbank.json`, 3,320): A2-2 2,317, A1 236, A5 222, A3-2 148, A3-1 129, B1 98, A2-1 85, A4 61, B2 24 (5 + 19 review-pass frames with `[CLAIM_A]/[CLAIM_B]`). LLM gate (`filter_seeds.py`: wrong code, needs outside context, audience/vote/panel, fragment, time ≠ ten seconds, two jobs; A5 must name who is stopped) + scene extraction → **627 scene seeds**: A3-2 148, A3-1 115, A2-2 99, A5 93, A1 45, A4 38, B1 37, A2-1 28, B2 24 (IQ2 247, OTD 227, Doha 124, Munk 9, SYN 20). Seeds mirror PRO↔CON with side words flipped; seeds with `[NAME]/[PLACE]/[ORG]/[EVENT]` unused.
- An earlier v9 pipeline (`_meta/gen`: 531 trigger+reply seeds, 496 LLM-written debates, MOD verbatim 95 %) was dropped because the LLM also wrote rules and timing.

## 5. Script generation (gen2, v7 → v8)

- **Python fixes** the selective-code menu, speech-length bands, D, seeds, names (163 M / 57 F), voices, motion (356 usable), word budgets. **LLM** (`gpt-5.6-luna`, one JSON call per debate, 468-word prompt) writes debater turns, an 8–12-word motion restatement, and CLAIM_A/B. Balanced menus: 50 debates → each selective code 26 times; D split three ways.
- **Budgets with slack** (LLM overshoots p90 23 %, max 64 %): short 44, full 66 = 44+[A4]+22, over 92 = 57+[A4]+35 words. Cut turns end on a hyphen; interruption slot 24 words; crossfire has surplus turns the mixer drops at D.
- **Failure modes → fixes.** Side confusion in crossfire dominated: 22 % of crossfire turns swapped in v7p (19/20 debates), 17 % v7q, 26 % v7r; side labels, TRUE/FALSE header, shorter prompt did nothing. Composite output keys (`"X12 Cecilia AGAINST"`) cut it to 4 % (v7s). Also fixed: B1 target bias (CON 73 %), A3-1 seed repetition (9 of 129 used, max 43 repeats), TTS-hostile Unicode (76/487 turns), weak B1/B2 events (10 → 1 per 10 debates).
- **Filter.** `check.py` 22 rules (budgets, dash, MOD share ≤ 0.28, PRO/CON time ratio ≤ 1.15, no audience/vote) + strict LLM judge (self-naming, wrong speaker, side switch, MOD echo, event validity, negatives) run by Claude subagents; luna-as-judge disagreed (9/33). `repair.py` rewrites flagged turns only.
- **Yield (v7, variable crossfire).** 50 generated → rules 47 → judge 22 → +9 repaired (18 calls) → 31 (`out/debates_v7_final.jsonl`).
- **Final batch (v8, crossfire fixed at 2:30, A3-1 states the start point, A5 interrupter resumes after the block, binary rubric).** 30 generated (30 calls, 0 failures) → rules 30/30 after four deterministic fixes (two closing lines mentioning listeners, one mis-oriented A5 seed, one stray self-name) → strict subagent judge **21/30** (`out/debates_v8_final.jsonl`). Fails: 6 with 1–4 side-swapped crossfire turns, 3 with a B2 pair that does not clash. Selective codes in the 21: A1 11 · A2-1 11 · A5 11 · B1 14 · B2 10. ≈200 luna calls overall.

## 6. Audio synthesis & mixing

- TTS: OmniVoice (`k2-fsa/OmniVoice`), per turn, cloned from 312 NaturalVoices/MSP-Podcast references with CER = 0 (178 M / 134 F); voice chosen by natural wpm near the required rate, gender kept, no reuse per debate. Target bands: short 18 s, in-time 26 s, edge 29 s, overrun 34 s.
- Trimming: Qwen3-ForcedAligner-0.6B anchors first/last word (fallbacks: energy, then untouched); energy-only trimming had cut real words in 8/331 fragments.
- Mix (`tts_mix.py`): gap 0.2 s (crossfire 0.2–1.0 s random); overlaps A4 1.2 s, A5 0.5 s, A1/A2-1/A3-2 0.8 s, barge-in 0.9 s. **Clock enforced:** A4 at 20 s, A1/A2-1 at 30.5 s, A4@xf at D−10, A3-2 at 2:30 (declared − realised = 0.00 s), A5 1.5 s after the interruption. Cut audio fades (0.25 s); `{id}_ext_a32.wav` keeps dropped speech so probes run ≥ 9 s past the deadline.

## 7. Evaluation protocol (final)

- **Free run.** The debater audio (all PRO/CON turns at their recorded times) plays from start to end; the model's own channel is open for the whole debate — nothing is forced into it and nothing is muted. Every model utterance is logged (onset time + text). The reference timeline (`probes.jsonl`) defines the triggers; the crossfire clock starts where the reference moderator finished opening it.
- **Timing** per trigger (first non-back-channel onset in [deadline−5, latest+3]): PREMATURE / ON_TIME / LATE / MISSED. Windows: A4 speaker-start+20 ±2 s; A4 crossfire start+140 ±2; A3-2 start+150 ±2; A1 and A2-1 speaker-start+30 [0, +2] (the 30 s are guaranteed); A2-2 and A3-1 [speech end, +2]; A5 [interruption start, +2]; B1 and B2 [turn end, +2].
- **Content** is binary per code, judged by an LLM from the utterance text: A4 says "ten seconds"; A2-2 hands over (name / other side / next); A3-1 announces the round change **and** the length; A3-2 says time is up **and** moves to closings; A1 / A2-1 stop the speaker for time; A5 restrains the interrupter; B1 points out the drift and steers back; B2 mentions both claims **and** asks the speaker to reconcile. Pass requires every criterion; the judge also records `predicted_label` (which action the utterance performed). Joint = ON_TIME ∧ pass. Utterances < 0.5 s or one word are back-channels and never attributed.
- **Non-trigger speech.** No separate negative probes. Every utterance that belongs to no trigger window is logged and judged against the system prompt: `backchannel` / `acceptable` / `violation` (a duty in the prompt is broken — stopping a speaker before time, policing crossfire interruptions, taking a side, declaring a winner, redirecting a speaker who was on the motion — or the utterance would derail the debate). Planted traps (a digression the speaker corrects, two compatible claims, a crossfire interruption, a speech that stops just before the limit) are kept as region labels for this analysis.
- **Reporting** per code: timing distribution, onset−deadline median/IQR, content pass, joint rate, predicted-label confusion; per debate: non-trigger utterance count and verdicts. Baselines: always silent; speak at every trigger. System prompt: 295 words, one sentence per scored behaviour. Target models: PersonaPlex base, RL-Seamless (TBD).
- The probe-replay mode (reference moderator teacher-forced up to a release point, then one trigger freed) is kept as a secondary tool for clean per-code timing.

## 8. Numbers at a glance

| item | value |
|---|---|
| Corpus | 4 corpora, 366 debates, 31,264 mod windows |
| Seeds: candidates → reviewed → gen2 scene seeds | 2,424 → 300 verdicts → 627 |
| Pilots (rules / judge pass) | v7p 15/20, 0/20 · v7q 6/10, 1/10 · v7r 8/10, 0/10 · v7s 9/10, 4/10 |
| v7 (variable crossfire) | 50 generated; rules 47; judge 22; +9 repaired → 31 |
| **v8 final (2:30 fixed)** | 30 generated; rules 30; judge **21 final** |
| Codes per final debate | 6–7 distinct (mean 6.7); 8–10 coded MOD turns (mean 9.5) |
| Selective codes in final 21 | A1 11 · A2-1 11 · A5 11 · B1 14 · B2 10 |
| Length (170-wpm simulation) | 789–917 words (mean 832); 290–322 s (mean 302 s) |
| Triggers (final 21, simulated timing) | 199: A1 11 · A2-1 11 · A2-2 31 · A3-1 21 · A3-2 21 · A4 48 · A4xf 21 · A5 11 · B1 14 · B2 10 |
| Realised durations, model scores | (TBD) |

## 9. Open issues / limitations

- Final set not yet synthesised at the time of writing; timings are 170-wpm simulations until TTS runs.
- In the free run the debater audio keeps the pauses where the reference moderator spoke, so a hand-off point is audible as a gap; this is inherent to static playback and is realistic (debaters wait), but it is a cue the model can exploit.
- A4 in the crossfire is the only long clock (140 s from the opening line); in a free run the model must also have opened the crossfire itself to know the start point — otherwise it can only infer it from the debaters.
- Both debaters share one channel; A5 and B2 require telling the voices apart.
- Residual 4 % side-swapped crossfire turns after generation; script filtering and content judging rely on LLM subagents.
- Seed review incomplete for A3-1/A3-2/A4; only 24 B2 frames; rare-code corpus labels are noisy; real chairs often cut without a prior ten-second cue, unlike our rule.
- MOD lines are human but recontextualised; debater content is synthetic; no audience.
