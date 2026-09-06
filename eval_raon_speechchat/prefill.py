#!/usr/bin/env python3
# khs_claude_code: builds the assistant history the model is told it already produced.
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

# the released checkpoint's special tokens. These are the values in this revision's
# config, and adopt_token_ids replaces them with whatever the loaded model reports, so a
# checkpoint that renumbers them cannot silently degrade the forcing into uniform
# sampling among the tokens the grammar mask happens to allow.
SIL_ID = 151672
BC_ID = 151673
PAD_ID = 151677
EPAD_ID = 151678


def adopt_token_ids(model):
    """Take the duplex token ids from the loaded checkpoint."""
    global SIL_ID, BC_ID, PAD_ID, EPAD_ID
    SIL_ID = int(getattr(model, "duplex_sil_token_id", SIL_ID))
    BC_ID = int(getattr(model, "duplex_bc_token_id", BC_ID))
    PAD_ID = int(getattr(model, "duplex_pad_token_id", PAD_ID))
    EPAD_ID = int(getattr(model, "duplex_end_pad_token_id", EPAD_ID))
    return {"SIL": SIL_ID, "BC": BC_ID, "PAD": PAD_ID, "EPAD": EPAD_ID}

LOOKAHEAD_FRAMES = 3       # measured, see tools/measure_text_audio_offset.py
TAIL_SEC = 6.0             # matches make_probe_audio.py


# ------------------------------------------------------------------ user audio
def build_user_track(root, timeline, probe, sr, exclude=("MOD",)):
    """The input channel with the moderator removed, at the official mix level.

    khs_claude_code: this reproduces make_probe_audio.py rather than approximating it,
    because the prefill arm is compared against the probe wav that script writes and any
    difference is confounded with the thing being measured.

      level      the official mix is exactly 0.5 times the sum of the isolated turns
                 (measured: rms_sum / rms_mix = 2.0000 on five debates), so summing at
                 unity would drive the model with a signal 6 dB hotter than the baseline
                 arm, straight into the speak or listen gate.

      the answer the official script zeroes the answer turn's TIME SPAN in the mix, which
                 also removes whatever other speaker overlaps it. Dropping only that
                 turn's file leaves the overlapping debater audible: on 48 of 143 probes
                 somebody else is speaking inside that span, and on 25 of them the
                 official file's hard cut lands inside the scoring window. The floor
                 going quiet is the one acoustic cue the timing metric rests on.

      the next   for an event or content probe the turn after the answer is silenced for
                 the length of the window, because a next speaker starting is itself the
                 answer.
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
    track *= 0.5                                   # the official mix level

    def silence(t0, t1):
        i, j = int(max(0.0, t0) * sr), int(min(t1, end) * sr)
        if j > i:
            track[i:j] = 0.0

    gt = turns.get(probe["before_turn"])
    if gt:
        silence(gt["start_sec"], gt["end_sec"])    # the answer, span not turn
    if probe.get("kind") in ("event", "content"):
        nxt = turns.get(probe["before_turn"] + 1)
        if nxt:
            silence(nxt["start_sec"], win_e)
    peak = float(np.abs(track).max())
    if peak > 1.0:
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
        # khs_claude_code: the lookahead is the offset of the TEXT token. The speaking phase has to
        # last until the AUDIO finishes, so the end is not shifted. Subtracting the
        # lookahead here would drop to SIL about 240 ms early and cut the tail off the
        # last word of every prefilled turn.
        last_audio = turn["start_sec"] + turn["words"][-1]["end"]
        end_frame = max(cursor - 1, int(round(last_audio * frame_rate)))
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
            local[f - 1] = EPAD_ID

        # khs_claude_code: two moderator turns can sit a fifth of a second apart, and the
        # three frame lookahead then pulls the later turn's onset onto the earlier one's
        # last PAD. Raising there aborted the run on 18 of the 143 probes. Pushing the
        # later turn far enough right to leave one silent frame between them keeps the
        # grammar valid and costs a few frames of alignment on the turns that collide,
        # which is recorded as shift_frames rather than hidden.
        if sched:
            need = max(sched) + 2 - (first - 1)     # one SIL frame, then the onset
            if need > 0:
                local = {f + need: t for f, t in local.items()}
                text_frames = {f + need for f in text_frames}
                first += need
                end_frame += need
                shift += need
        for f, t in local.items():
            sched[f] = t
        spans.append({"turn": turn["turn"], "start_frame": first - 1,
                      "end_frame": end_frame, "shift_frames": shift,
                      "start_sec": round((first - 1) / frame_rate, 3),
                      "end_sec": round((end_frame + 1) / frame_rate, 3),
                      "text": turn["text"]})
    return sched, spans


def encode_turn_codes(model, wav_path, sample_rate, num_code_groups):
    """The real moderator audio, in the model's own audio code space.

    KHS: forcing the text alone leaves the acoustic side to the model, and on this model
    it often does not follow: measured over six draws of the same eighteen second turn
    the forced span came out 11 to 94 percent voiced, median 43. A history whose text is
    right and whose audio is silent is not a history. Encoding the real turn audio with
    the model's own tokenizer and forcing those codes removes the failure at its source,
    and it also puts the ORIGINAL recording into the history rather than a re synthesis.
    """
    import librosa
    import torch
    # khs_claude_code: forcing a single code row per frame is only correct while the
    # semantic and acoustic codebooks share a frame. A checkpoint with a non zero
    # acoustic delay would split them and every forced frame would be wrong with no
    # visible symptom, so the assumption is pinned rather than left implicit.
    if int(getattr(model, "max_delay", 0)) != 0:
        raise NotImplementedError(
            f"this checkpoint has acoustic delay {model.max_delay}; forcing audio codes "
            f"one row per frame assumes no delay")
    wav, _ = librosa.load(str(wav_path), sr=sample_rate, mono=True)
    a = torch.tensor(wav, dtype=torch.float32, device=model.device)[None, None]
    lengths = torch.tensor([a.shape[-1]], device=model.device)
    with torch.inference_mode():
        out = model.tokenize_audio(audio=a, audio_lengths=lengths,
                                   num_code_groups=num_code_groups)
    return out.audio_codes[0]                       # [frames, num_code_groups]


def build_code_schedule(model, root, history, spans, frame_rate, sample_rate,
                        num_code_groups):
    """frame index -> the audio codes of the real moderator audio at that frame.

    The codes sit on the AUDIO timeline, not the text timeline, so no lookahead is
    applied here. A turn that had to be shifted to fit at the start of the stream is
    shifted by the same amount, so its text and its audio stay together.
    """
    by_turn = {sp["turn"]: sp for sp in spans}
    sched = {}
    for turn in history:
        sp = by_turn.get(turn["turn"])
        if sp is None:
            continue
        codes = encode_turn_codes(model, root / turn["audio"], sample_rate,
                                  num_code_groups)
        # khs_claude_code: minus one because the pipeline hands back the PREVIOUS frame's
        # audio. init_duplex_decoding_state pushes a row without pulling, and every step
        # then pushes one and pulls the oldest, so a code written at hook frame f is
        # heard at wav frame f + 1. Cross correlating a prefilled run against the source
        # recording peaked at exactly +1 frame before this correction.
        a0 = int(round(turn["start_sec"] * frame_rate)) + sp["shift_frames"] - 1
        for t in range(codes.shape[0]):
            f = a0 + t
            if sp["start_frame"] <= f <= sp["end_frame"]:
                sched[f] = codes[t]
        # khs_claude_code: the span opens a few frames before the recording starts,
        # because the text runs ahead of its audio, and closes a frame or two after it
        # ends. Those frames would otherwise carry codes the model invented, so the
        # onset of every prefilled turn would not be the original recording, and the
        # near silence there would drag the voiced fraction down and trigger redraws.
        # They are filled with the tokenizer's own silence instead.
        silence = model.get_silence_codes(codes.device)
        for f in range(sp["start_frame"], sp["end_frame"] + 1):
            sched.setdefault(f, silence)
    return sched


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


def voiced_fraction(frame_log, spans, floor=0.001):
    """How much of the forced history actually came out as sound.

    KHS: forcing the text does not guarantee the acoustic side follows. On this data the
    same eighteen second turn came out 7 percent silent on one run and 67 percent silent
    on another, with the audio collapsing partway through and never recovering. Nothing
    in the frame kinds shows that, so it is measured from the decoder's own output level
    and reported per turn. A run where this is low has a history the model can read but
    not hear, which is not the experiment.
    """
    import re
    line = re.compile(r"^\[(\w+)\] f=(\d+) text=.*? out_rms=([\d.eE+-]+) ")
    rms = {}
    for row in open(frame_log):
        m = line.match(row.strip())
        if m:
            rms[int(m.group(2))] = float(m.group(3))
    out = []
    for sp in spans:
        vals = [rms.get(f, 0.0) for f in range(sp["start_frame"], sp["end_frame"] + 1)]
        vals = [v for v in vals if v is not None]
        voiced = sum(1 for v in vals if v >= floor)
        out.append({"turn": sp["turn"], "frames": len(vals),
                    "voiced": round(voiced / max(1, len(vals)), 3)})
    overall = ([v for sp in out for v in [sp["voiced"]] * sp["frames"]])
    return {"per_turn": out,
            "voiced_overall": round(sum(overall) / len(overall), 3) if overall else None}


def describe(sched, spans, release_frame, frame_rate=12.5):
    kinds = {"SIL": 0, "PAD": 0, "EPAD": 0, "TEXT": 0}
    for f in range(release_frame):
        t = sched.get(f, SIL_ID)
        kinds["SIL" if t == SIL_ID else "PAD" if t == PAD_ID
              else "EPAD" if t == EPAD_ID else "TEXT"] += 1
    return {"release_frame": release_frame,
            "release_sec": round(release_frame / frame_rate, 3),
            "turns_prefilled": len(spans), "frames": kinds, "spans": spans}
