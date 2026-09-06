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
#   How far ahead of its audio the model emits text.   Measured with
#   tools/measure_text_audio_offset.py on the model's own output: the median is three
#   frames, 240 ms, and it does not change between the first word of an utterance and
#   the later ones. The technical report states "one-frame text lookahead" for a
#   training stage, which is a statement about how speech tokens are conditioned, not
#   about the distance to audible audio. The measured number is the one that reproduces
#   what the model itself does, so that is the one used.
#
#   What the token stream is allowed to look like.   Read out of the released model's
#   own logit mask, not the paper: from SIL only SIL, EPAD or BC; right after EPAD only
#   a real text token; after a text token, text, PAD, EPAD or SIL; on a PAD frame, PAD,
#   EPAD or SIL. A schedule that violates this makes every logit negative infinity and
#   the model silently emits garbage, so validate_schedule refuses to run one.
#
# The user channel changes too. If the moderator is in the assistant channel it must not
# also be in the input, so the input is rebuilt from the debater turns alone.
"""Build the assistant prefill schedule and the matching user audio."""
import json
import pathlib

import numpy as np

# from the released checkpoint's special tokens
SIL_ID = 151672
BC_ID = 151673
PAD_ID = 151677
EPAD_ID = 151678

LOOKAHEAD_FRAMES = 3       # measured, see tools/measure_text_audio_offset.py
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
        if t["speaker"] in exclude or t["start_sec"] >= end:
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
    """The aligned moderator turns that happened before the decision point."""
    out = []
    for t in timeline["turns"]:
        if t["speaker"] != "MOD" or t["i"] >= before_turn:
            continue
        a = alignments["turns"].get(f'{debate_id}/{t["i"]}')
        if a and a["words"]:
            out.append(a)
    return out


def build_schedule(history, tokenizer, frame_rate=12.5,
                   lookahead_frames=LOOKAHEAD_FRAMES, min_frame=2):
    """frame index -> token id the model is forced to emit. Frames left out mean SIL.

    Each word's text token lands lookahead_frames before the frame its audio starts on,
    and PAD fills the frames inside an utterance that carry no new text. That is the
    report's "temporal consistency ... when the number of text tokens is smaller than
    the number of speech tokens".

    EPAD before every text token that follows a PAD or a silence. This is not
    decoration: the released model's own logit mask allows only PAD, EPAD or SIL after a
    PAD frame, so a text token placed straight after PAD is masked to negative infinity
    along with everything else and the model emits whatever index zero happens to be.
    EPAD is what the report calls BOW, "a special token emitted immediately before each
    assistant text token", and the grammar is where that shows up in the release.

    min_frame exists because the first turn of a debate starts at second zero, so
    subtracting the lookahead would put its text before the stream begins. Such a turn is
    shifted right just enough to fit, which costs it a few frames of lookahead and is
    reported as shift_frames rather than hidden.
    """
    sched, spans = {}, []
    for turn in history:
        local, text_frames, first, cursor = {}, set(), None, None
        for w in turn["words"]:
            audio_frame = int(round((turn["start_sec"] + w["start"]) * frame_rate))
            want = audio_frame - lookahead_frames
            f = want if cursor is None else max(want, cursor)
            ids = tokenizer.encode(" " + w["text"].strip(), add_special_tokens=False)
            if not ids:
                continue
            for k, tid in enumerate(ids):
                local[f + k] = tid
                text_frames.add(f + k)
            cursor = f + len(ids)
            if first is None:
                first = f
        if first is None:
            continue
        last_audio = turn["start_sec"] + turn["words"][-1]["end"]
        end_frame = max(cursor - 1,
                        int(round(last_audio * frame_rate)) - lookahead_frames)
        for f in range(first, end_frame + 1):
            local.setdefault(f, PAD_ID)

        # one free frame in front for the first onset, plus room for min_frame
        shift = max(0, min_frame - (first - 1))
        if shift:
            local = {f + shift: t for f, t in local.items()}
            text_frames = {f + shift for f in text_frames}
            first += shift
            end_frame += shift
        local[first - 1] = EPAD_ID

        # every later text token that follows a PAD needs its own EPAD, and the PAD
        # immediately before it is the frame to spend on that
        for f in sorted(text_frames):
            if f - 1 in text_frames or local.get(f - 1) == EPAD_ID:
                continue
            if local.get(f - 1) == PAD_ID:
                local[f - 1] = EPAD_ID
            else:
                local[f - 1] = EPAD_ID          # start of turn, already free

        for f, t in local.items():
            sched[f] = t
        spans.append({"turn": turn["turn"], "start_frame": first - 1,
                      "end_frame": end_frame, "shift_frames": shift,
                      "start_sec": round((first - 1) / frame_rate, 3),
                      "end_sec": round((end_frame + 1) / frame_rate, 3),
                      "text": turn["text"]})
    return sched, spans


def validate_schedule(sched, release_frame):
    """Walk the released model's own grammar over the schedule, exactly as it is written.

    This mirrors DuplexStateManager.apply_logit_mask rather than paraphrasing it:

        SIL phase                 SIL, EPAD or BC
        SPEECH, last was EPAD/BC  a real text token only
        SPEECH, last was text     text, PAD, EPAD or SIL
        SPEECH, last was PAD      PAD, EPAD or SIL, no text

    Worth doing rather than trusting the construction. An invalid token is masked to
    negative infinity together with everything else, and the model then emits whatever
    index zero happens to be, which reads as fluent nonsense rather than as an error.
    """
    STRUCT = {SIL_ID, PAD_ID, EPAD_ID, BC_ID}
    phase, context = "SIL", None
    for f in range(release_frame):
        tid = sched.get(f, SIL_ID)
        if phase == "SIL":
            if tid not in (SIL_ID, EPAD_ID, BC_ID):
                return f, f"text token while silent, only SIL, EPAD or BC allowed"
            phase = "SIL" if tid == SIL_ID else "SPEECH"
            context = None if tid == SIL_ID else tid
            continue
        if context in (EPAD_ID, BC_ID):
            if tid in STRUCT:
                return f, "only a real text token may follow EPAD or BC"
        elif context is None:                       # the last frame was PAD
            if tid not in (PAD_ID, EPAD_ID, SIL_ID):
                return f, "text after PAD, an EPAD must come first"
        else:                                       # the last frame was text
            if tid == BC_ID:
                return f, "BC is only reachable from the silent phase"
        if tid == SIL_ID:
            phase, context = "SIL", None
        elif tid == PAD_ID:
            context = None
        else:
            context = tid
    return None, None


def load_alignments(path):
    return json.load(open(path))


def describe(sched, spans, release_frame, frame_rate=12.5):
    kinds = {"SIL": 0, "PAD": 0, "EPAD": 0, "TEXT": 0}
    for f in range(release_frame):
        t = sched.get(f, SIL_ID)
        kinds["SIL" if t == SIL_ID else "PAD" if t == PAD_ID
              else "EPAD" if t == EPAD_ID else "TEXT"] += 1
    return {"release_frame": release_frame,
            "release_sec": round(release_frame / frame_rate, 3),
            "turns_prefilled": len(spans), "frames": kinds, "spans": spans}
