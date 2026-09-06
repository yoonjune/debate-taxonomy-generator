#!/usr/bin/env python3
# KHS: builds the assistant history the model is told it already produced.
#
# The default protocol plays the finished mix at the model and lets it listen. The
# moderator's earlier turns arrive on the input channel, so the model hears its own past
# as a third party and does not know it has already spoken. This module does the other
# thing: it puts those turns into the ASSISTANT channel, frame by frame, as if the model
# had generated them, and only then lets it decide what to do next.
#
# Three pieces are needed and all three are measured or read rather than guessed.
#
#   Where each word is spoken.   From tools/build_alignments.py, which force aligns each
#   moderator turn against its own isolated audio in data_sample/audio/turns. The mix
#   cannot be used because the moderator deliberately overlaps a debater there.
#
#   How far ahead of its audio the model emits text.   The technical report describes
#   TAIL, which at training time assigns a text token to the chunk its start time falls
#   in, plus "a bounded look-ahead mechanism: the speech tokens of the last few text
#   tokens in chunk k are deferred to chunk k+1". Neither the deferral nor what the
#   released model does at inference is quantified, so it was measured with
#   tools/measure_text_audio_offset.py on the model's own output: the median is one
#   chunk, about 1.1 s, with 69 percent of words landing at exactly minus one chunk.
#
#   What a chunk is allowed to look like.   Read out of the released model: a silent
#   chunk is the single token <|listen|>, and a speaking chunk is <|speak|> followed by
#   text tokens and closed by <|chunk_eos|>, with <|turn_eos|> before the close on the
#   last chunk of an utterance. At most max_new_speak_tokens_per_chunk tokens fit, which
#   is 20 by default, so validate_schedule refuses a chunk that overflows.
#
# The user channel changes too. If the moderator is in the assistant channel it must not
# also be in the input, so the input is rebuilt from the debater turns alone.
"""Build the assistant prefill schedule and the matching user audio."""
import json
import pathlib

import numpy as np

LOOKAHEAD_CHUNKS = 1       # measured, see tools/measure_text_audio_offset.py
TAIL_SEC = 6.0             # matches make_probe_audio.py


# ------------------------------------------------------------------ user audio
def build_user_track(root, timeline, probe, sr, exclude=("MOD",)):
    """The input channel with the moderator removed.

    Rebuilt from the isolated turn files rather than by subtracting from the mix, since
    the turns overlap on purpose and there is nothing to subtract. Debater turns are
    summed at their own start times, so a crossfire interruption still overlaps.

    The leak handling of make_probe_audio.py is kept: for an event or content probe the
    turn after the answer is silenced for the length of the window, because a next
    speaker starting is itself the answer.
    """
    import librosa
    win_e = (probe["t_latest"] if probe["t_latest"] is not None
             else probe["context_end_sec"] + 3.0)
    end = win_e + TAIL_SEC
    track = np.zeros(int(end * sr) + 1, dtype=np.float32)
    turns = {t["i"]: t for t in timeline["turns"]}
    for t in timeline["turns"]:
        # KHS: the answer turn goes whatever speaker holds it. make_probe_audio.py
        # silences tl[before_turn] unconditionally, and on this data every negative
        # probe's before_turn is a debater, not the moderator. Removing only moderator
        # audio would leave the debater talking straight through the decision point,
        # which is itself the cue that nobody intervened, and would make all 66 silence
        # probes trivially easy.
        if t["i"] == probe["before_turn"] or t["speaker"] in exclude or t["start_sec"] >= end:
            continue
        p = root / "audio/turns" / f'{timeline["debate_id"]}_{t["i"]:03d}.mp3'
        if not p.exists():
            continue
        a, _ = librosa.load(str(p), sr=sr, mono=True)
        i = int(t["start_sec"] * sr)
        j = min(len(track), i + len(a))
        if j > i:
            track[i:j] += a[: j - i].astype(np.float32)
    if probe.get("kind") in ("event", "content"):
        nxt = turns.get(probe["before_turn"] + 1)
        if nxt:
            i, j = int(nxt["start_sec"] * sr), int(min(win_e, end) * sr)
            if j > i:
                track[i:j] = 0.0
    peak = float(np.abs(track).max())
    if peak > 1.0:                       # summing turns can clip
        track /= peak
    return track[: int(end * sr)]


# ------------------------------------------------------------- assistant track
def moderator_history(timeline, alignments, debate_id, before_turn):
    """The aligned moderator turns that happened before the decision point.

    A turn with no alignment is a hard error rather than a skip. The user track removes
    every moderator turn, so an unaligned one would be neither heard nor prefilled: a
    hole in the history with nothing to show for it. That can happen from a debate
    scoped alignments file, an alignment failure or a missing turn mp3, and it should
    stop the run rather than quietly change the experiment.
    """
    out, missing = [], []
    for t in timeline["turns"]:
        if t["speaker"] != "MOD" or t["i"] >= before_turn:
            continue
        a = alignments["turns"].get(f'{debate_id}/{t["i"]}')
        if a and a["words"]:
            out.append(a)
        else:
            missing.append(t["i"])
    if missing:
        raise KeyError(f"{debate_id}: no alignment for moderator turns {missing}. "
                       f"Rerun tools/build_alignments.py for this debate.")
    return out


def build_schedule(history, tokenizer, ids, chunk_seconds=1.0,
                   lookahead_chunks=LOOKAHEAD_CHUNKS, max_tokens=20):
    """chunk index -> the exact token sequence the model is forced to emit.

    TAIL assigns a text token to the chunk its start time falls in. The measured offset
    says the released model runs one chunk ahead of its own audio, so a word whose audio
    starts in chunk c has its text placed in chunk c minus lookahead_chunks.

    A chunk that says nothing is the single token <|listen|>. A chunk that speaks is
    <|speak|>, then its text, then <|chunk_eos|>, with <|turn_eos|> before the close on
    the last chunk of an utterance. Overflow past max_tokens spills into the next chunk
    rather than being dropped, which keeps the words and moves them late.
    """
    buckets, spans, owner = {}, [], {}
    for turn in history:
        touched = []
        for w in turn["words"]:
            t = turn["start_sec"] + w["start"]
            c = max(0, int(t // chunk_seconds) - lookahead_chunks)
            toks = tokenizer.encode(" " + w["text"].strip(), add_special_tokens=False)
            if not toks:
                continue
            room = max_tokens - 3 - len(buckets.get(c, []))       # speak, turn_eos, eos
            while room < len(toks):
                c += 1
                room = max_tokens - 3 - len(buckets.get(c, []))
            if c in owner and owner[c] != turn["turn"]:
                raise ValueError(f"turn {turn['turn']} lands in chunk {c}, already held "
                                 f"by turn {owner[c]}. Two utterances would fuse.")
            owner[c] = turn["turn"]
            buckets.setdefault(c, []).extend(toks)
            touched.append(c)
        if not touched:
            continue
        lo, hi = min(touched), max(touched)
        spans.append({"turn": turn["turn"], "start_chunk": lo, "end_chunk": hi,
                      "start_sec": round(lo * chunk_seconds, 3),
                      "end_sec": round((hi + 1) * chunk_seconds, 3),
                      "text": turn["text"], "last_chunk": hi})

    last_chunks = {s["last_chunk"] for s in spans}
    sched = {}
    for c, toks in buckets.items():
        seq = [ids["speak"]] + list(toks)
        if c in last_chunks:
            seq.append(ids["turn_eos"])
        seq.append(ids["chunk_eos"])
        sched[c] = seq
    release = (max(sched) + 1) if sched else 0
    for c in range(release):
        sched.setdefault(c, [ids["listen"]])
    return sched, spans, release


def validate_schedule(sched, ids, max_tokens=20):
    """Check each chunk against what the released model's loop will accept.

    A silent chunk is exactly one <|listen|>. A speaking chunk opens with <|speak|>,
    closes with <|chunk_eos|>, and fits inside max_new_speak_tokens_per_chunk. The loop
    stops at a terminator, so a sequence that never reaches one would run to the cap and
    swallow the following chunk's tokens.
    """
    for c in sorted(sched):
        seq = sched[c]
        if not seq:
            return c, "empty chunk"
        if seq[0] == ids["listen"]:
            if len(seq) != 1:
                return c, "a listen chunk must be exactly one token"
            continue
        if seq[0] != ids["speak"]:
            return c, "a speaking chunk must open with the speak token"
        if seq[-1] != ids["chunk_eos"]:
            return c, "a speaking chunk must close with the chunk eos token"
        if len(seq) > max_tokens:
            return c, f"{len(seq)} tokens, over the {max_tokens} cap"
        for t in seq[1:-1]:
            if t in (ids["listen"], ids["chunk_eos"], ids["speak"]):
                return c, "a terminator inside the chunk would end it early"
    return None, None


def load_alignments(path):
    return json.load(open(path))


def describe(sched, spans, release, ids, chunk_seconds=1.0):
    speak = sum(1 for c in range(release) if sched.get(c, [ids["listen"]])[0] != ids["listen"])
    return {"release_chunk": release,
            "release_sec": round(release * chunk_seconds, 3),
            "turns_prefilled": len(spans),
            "chunks": {"speaking": speak, "listening": release - speak},
            "spans": spans}
