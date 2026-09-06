#!/usr/bin/env python3
# khs_claude_code: drives the official Raon-SpeechChat duplex path over a debate probe set.
#
# The official code is called and not modified. RaonPipeline.duplex already accepts a
# system prompt and a speaker reference wav, so the driver passes those and leaves every
# sampling parameter unset, which makes duplex() fall back to the values in the official
# config/duplex_infer.yaml. Each of those is exposed as a flag defaulting to None, so a
# later sweep is a command line and not an edit, and the effective value of everything
# is written to run_config.json beside the results.
#
# Timing comes from the frame log the official code writes. Each line carries the duplex
# state machine phase for that frame, SIL or SPEECH. The frame rate is read from the
# processor rather than hard coded, so a checkpoint with a different rate cannot
# silently shift every timestamp.
"""Run the Raon-SpeechChat full duplex path over a debate probe set.

  python run_probes.py --ckpt ckpt/Raon-SpeechChat-9B --limit 3
  python run_probes.py --ckpt ckpt/Raon-SpeechChat-9B
  python run_probes.py --ckpt ... --tag sil03 --sil-penalty 0.3
  python run_probes.py --ckpt ... --tag noref --no-reference --kinds negative
"""
import argparse
import ast
import json
import os
import pathlib
import re
import sys
import time

# khs_claude_code: the official duplex loop prints a tqdm bar for every frame, which is thousands of
# lines per probe in a log file. tqdm reads this at construction, so it is set before the
# pipeline is imported; our own progress bar passes disable=False to opt back in.
os.environ.setdefault("TQDM_DISABLE", "1")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import prefill                                                    # noqa: E402
from probe_data import ProbeSet                                   # noqa: E402

# [SIL] f=0 text=- out_rms=0.0000 in_rms=0.0123 ntok=2
FRAME_LINE = re.compile(
    r"^\[(?P<phase>\w+)\] f=(?P<f>\d+) text=(?P<text>.*?) "
    r"out_rms=(?P<out>[\d.eE+-]+) in_rms=(?P<in>[\d.eE+-]+) ntok=(?P<ntok>\d+)\s*$")

# khs_claude_code: Raon has an explicit backchannel state, and the token shows up in the frame log
# text. A backchannel is "mm-hmm" while somebody else holds the floor. It is not a
# moderator intervention, and counting it as one would make every probe look like the
# model spoke. Segments carrying it are flagged and left out of the onset search, and
# --count-backchannels puts them back for anyone who disagrees.
BACKCHANNEL_TOKEN = "<|audio_output_backchannel|>"

# every sampling knob duplex() accepts, with the official default it falls back to
OFFICIAL_DEFAULTS = {"temperature": 0.9, "top_p": 0.95, "top_k": 66,
                     "sil_penalty": 0.0, "bc_penalty": 0.0, "eos_penalty": 0.0,
                     "speak_first": False}


def widen_decoder_timeout(RaonPipeline, seconds):
    """Give the audio decoder subprocess longer than one second per frame.

    KHS: the only change this branch makes to official behaviour, and it changes
    tolerance rather than results. Raon decodes audio in a separate process, and the
    official drain_to waits timeout_per_item=1.0 for each frame, then returns nothing,
    and pull_audio asserts that it got exactly one result. One second is generous for
    the interactive demo the code was written for. It is not generous on a shared batch
    node: this one has 16 cores under a load average around 45, and the worker's first
    decode after process start needs more than that, so the run dies on frame zero of
    the first probe. Waiting longer cannot change what is decoded, only whether we wait
    for it.
    """
    module = sys.modules[RaonPipeline.__module__]
    original = module.ConcurrentAudioDecoder.drain_to

    def drain_to(self, max_pending, stream_id, timeout_per_item=seconds):
        return original(self, max_pending, stream_id, timeout_per_item)

    module.ConcurrentAudioDecoder.drain_to = drain_to
    return module


def warm_up(pipe, out_dir, seconds=2.0):
    """One throwaway duplex pass, so the first real probe does not pay for a cold
    decoder process, cuDNN autotuning and the speaker encoder all at once."""
    import numpy as np
    import soundfile as sf
    d = out_dir / ".warmup"
    d.mkdir(parents=True, exist_ok=True)
    wav = d / "silence.wav"
    sr = int(pipe.processor.sampling_rate)
    sf.write(str(wav), np.zeros(int(sr * seconds), dtype="float32"), sr)
    t0 = time.time()
    pipe.duplex(audio_input=pipe.load_audio(str(wav)), output_dir=str(d),
                system_prompt="warm up")
    for f in d.glob("*"):
        f.unlink(missing_ok=True)
    return time.time() - t0


def install_prefill_hook(model):
    """Let the caller decide what the model emits, frame by frame, up to a release point.

    KHS: this is the whole of the prefill modification, and it extends a path the
    official code already has rather than adding one. duplex_decoding_step overwrites
    text_logits itself when forced_sil_remaining is set, and it reads the text
    prediction from a fixed position, new_logits[:, -2]. This wraps the function that
    consumes those logits and, while the frame index is below the release point,
    replaces them with a one hot for the scheduled token. Everything downstream, the
    state machine, the grammar mask, the audio codes, is the official code untouched.

    Returns a control dict. Set schedule and release per probe, and reset frame to zero
    before each duplex call, since the loop starts counting from the first frame again.
    """
    import torch
    original = model._update_duplex_sequences_and_generate_audio_codes
    ctl = {"schedule": None, "release": 0, "frame": 0, "original": original}

    def wrapped(new_logits, **kw):
        f = ctl["frame"]
        ctl["frame"] = f + 1
        # khs_claude_code: frame minus one is the call init_duplex_decoding_state makes
        # for the official forced first prediction. Overwriting it with SIL made
        # --speak-first a silent no op while run_config still recorded it as set.
        forcing = ctl["schedule"] is not None and 0 <= f < ctl["release"]
        if forcing:
            token = ctl["schedule"].get(f, prefill.SIL_ID)
            forced = torch.full_like(new_logits, -1e9)
            forced[:, -2, token] = 0.0
            new_logits = forced
        out = original(new_logits=new_logits, **kw)
        codes = ctl.get("codes")
        if forcing and codes is not None:
            row = codes.get(f)
            # khs_claude_code: audio_codes grows by one row on a speaking frame, and that row is
            # both what the decoder speaks and what the next step conditions on. When
            # the real moderator audio has codes for this frame, they replace the ones
            # the model just invented, so the history is the original recording rather
            # than a re synthesis that sometimes comes out silent.
            if row is not None:
                ac = out[3]
                if ac is not None and ac.shape[1] > kw["audio_codes"].shape[1]:
                    ac[0, -1] = row.to(device=ac.device, dtype=ac.dtype)
        return out

    model._update_duplex_sequences_and_generate_audio_codes = wrapped
    return ctl


def parse_frame_log(path, frame_rate):
    """Every stretch of speech in the probe, not only the first.

    KHS: taking the first SPEECH frame alone throws away the answer. A full duplex model
    can speak more than once in one probe, and it does: on this data Raon opens by
    announcing the debate format at frame one, because the system prompt tells it to do
    that at the start, and every probe begins in the middle of a debate where the format
    was already announced. Reporting only that first onset would hide a correct
    intervention thirty seconds later. So every contiguous run of SPEECH frames is
    returned with its own start, end and text, and the scorer picks.

    spoke_at stays the first onset so a reader who wants one number still gets one.
    """
    frames = []
    with open(path) as f:
        for line in f:
            m = FRAME_LINE.match(line.rstrip("\n"))
            if not m:
                continue
            t = m.group("text")
            if t != "-":
                try:
                    t = ast.literal_eval(t)
                except (ValueError, SyntaxError):
                    pass
            else:
                t = ""
            frames.append((int(m.group("f")), m.group("phase"), t,
                           float(m.group("out"))))

    to_sec = lambda i: round(i / frame_rate, 3)
    segments, cur = [], None
    first_audio = None
    for idx, phase, text, out_rms in frames:
        if out_rms > 0.0 and first_audio is None:
            first_audio = idx
        if phase == "SPEECH":
            if cur is None:
                cur = {"start": to_sec(idx), "start_frame": idx,
                       "end": to_sec(idx + 1), "end_frame": idx, "text": ""}
            cur["end"], cur["end_frame"] = to_sec(idx + 1), idx
            cur["text"] += text
        elif cur is not None:
            segments.append(cur)
            cur = None
    if cur is not None:
        segments.append(cur)
    for seg in segments:
        raw = seg["text"]
        seg["is_backchannel"] = BACKCHANNEL_TOKEN in raw
        seg["text"] = raw.replace(BACKCHANNEL_TOKEN, "").strip() or None
        seg["duration"] = round(seg["end"] - seg["start"], 3)

    return {"spoke_at": segments[0]["start"] if segments else None,
            "first_speech_frame": segments[0]["start_frame"] if segments else None,
            "audible_at": to_sec(first_audio) if first_audio is not None else None,
            "first_audio_frame": first_audio,
            "text": " ".join(s["text"] for s in segments if s["text"]) or None,
            "segments": segments, "n_segments": len(segments),
            "speech_frames": sum(s["end_frame"] - s["start_frame"] + 1 for s in segments),
            "n_frames": len(frames)}


def window_view(segments, item, count_backchannels=False, release_sec=0.0):
    """Where the model's onsets fall relative to the scoring window.

    Not a score, just the arithmetic a reader would otherwise redo, and the reason it is
    here is that a full duplex model speaks many times in one probe. The first onset is
    usually not the interesting one.

      onset_in_window  the first onset inside [t_earliest, t_latest], or None
      nearest_onset    the onset closest to t_deadline, whether or not it is in window
      onset_offset     nearest_onset minus t_deadline, so sign is early or late

    nearest_onset matters at the boundary. On this data an onset landed 0.08 s, one
    frame, before t_earliest. Whether that counts is the scorer's call, not this file's,
    so both the verdict and the distance are reported.
    """
    # a segment that starts before the release point was put there by us, not chosen by
    # the model, so it cannot count as an intervention
    usable = [s for s in segments
              if (count_backchannels or not s["is_backchannel"])
              and s["start"] >= release_sec]
    lo, hi, dl = item["t_earliest"], item["t_latest"], item["t_deadline"]
    out = {"onset_in_window": None, "nearest_onset": None, "onset_offset": None}
    if dl is None or not usable:
        return out
    for seg in usable:
        if lo is not None and hi is not None and lo <= seg["start"] <= hi:
            out["onset_in_window"] = seg["start"]
            break
    near = min(usable, key=lambda s: abs(s["start"] - dl))
    out["nearest_onset"] = near["start"]
    out["onset_offset"] = round(near["start"] - dl, 3)
    return out


def sampling_kwargs(args):
    """Only the knobs actually set on the command line, so the rest stay official."""
    return {k: getattr(args, k) for k in OFFICIAL_DEFAULTS
            if getattr(args, k) is not None}


def prepare_prefill(pipe, item, args, probe_dir, ctl):
    """Build this probe's assistant schedule and the matching moderator free input."""
    import soundfile as sf
    fr = float(pipe.processor.frame_rate)
    sr = int(pipe.processor.sampling_rate)
    history = prefill.moderator_history(item["timeline"], item["alignments"],
                                        item["debate_id"], item["probe"]["before_turn"])
    sched, spans = prefill.build_schedule(history, pipe.processor.tokenizer, fr,
                                          args.lookahead_frames)
    release = (max(sched) + 1) if sched else 0
    bad_frame, why = prefill.validate_schedule(sched, release)
    if bad_frame is not None:
        raise ValueError(f"invalid prefill schedule at frame {bad_frame}: {why}")

    track = prefill.build_user_track(item["root"], item["timeline"], item["probe"], sr)
    wav = probe_dir / "user_input.wav"
    sf.write(str(wav), track, sr)

    # khs_claude_code: init_duplex_decoding_state calls the wrapped function once, for the forced
    # first prediction, before the frame loop starts. Counting from zero would put every
    # scheduled frame one frame early, which was verified against the frame log: a
    # schedule with EPAD at frame 2 landed at log frame 1. Starting at minus one lines
    # the counter up with the log.
    prefill.adopt_token_ids(pipe.model)     # khs_claude_code: ids from the checkpoint
    ctl["schedule"], ctl["release"], ctl["frame"] = sched, release, -1
    ctl["codes"] = None
    if args.force_audio_codes:
        groups = int(pipe.model.num_code_groups)
        ctl["codes"] = prefill.build_code_schedule(
            pipe.model, item["root"], history, spans, fr, sr, groups)
    info = prefill.describe(sched, spans, release, fr)
    info["user_audio_seconds"] = round(len(track) / sr, 3)
    return wav, info


def run_one(pipe, item, args, out_dir, sampling, ctl=None):
    probe_dir = out_dir / "probes" / item["probe_id"]
    probe_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    audio_path, info = item["audio"], None
    if ctl is not None:
        audio_path, info = prepare_prefill(pipe, item, args, probe_dir, ctl)

    kwargs = dict(sampling)
    kwargs["system_prompt"] = item["system_prompt"]        # khs_claude_code: benchmark prompt
    if item["reference_wav"] is not None:
        kwargs["speaker_audio"] = str(item["reference_wav"])

    frame_rate = float(pipe.processor.frame_rate)
    # khs_claude_code: forcing the text does not guarantee the acoustic side follows. On this model
    # the same forced turn came out 11 percent voiced on one draw and 93 percent on
    # another, with the audio collapsing partway through and never recovering. A history
    # the model can read but not hear is not the experiment, so a draw below min_voiced
    # is discarded and redrawn rather than measured. Attempts are recorded, and a probe
    # that never clears the bar is reported rather than quietly kept.
    attempts = 0
    while True:
        attempts += 1
        if ctl is not None:
            ctl["frame"] = -1
        summary = pipe.duplex(audio_input=pipe.load_audio(str(audio_path)),
                              output_dir=str(probe_dir), **kwargs)
        parsed = parse_frame_log(probe_dir / "frame_log.txt", frame_rate)
        if info is None:
            break
        info.update(prefill.voiced_fraction(probe_dir / "frame_log.txt", info["spans"]))
        info["attempts"] = attempts
        info["min_voiced"] = args.min_voiced
        ok = (info.get("voiced_overall") or 0.0) >= args.min_voiced
        info["voiced_ok"] = bool(ok)
        if ok or attempts > args.prefill_retries:
            break

    if not args.keep_stereo:
        # the official code also writes a full length stereo mix of user and assistant,
        # about 14 MB per probe and not needed for scoring
        (probe_dir / "user_assistant.wav").unlink(missing_ok=True)

    # khs_claude_code: every field below describes what the MODEL did. Segments we forced are not
    # the model's choices, so they are split out rather than counted: without this
    # spoke is True and spoke_at is 0.08 on every probe in prefill mode, which is the
    # forced onset and says nothing.
    # khs_claude_code: split on the frame the segment STARTS on against the release
    # frame, not on a time that can fall inside a segment. And a backchannel is not an
    # intervention, which this file says in its own header: counting one made spoke true
    # with text null on probes where an mm-hmm under a debater is the expected duplex
    # behaviour, so the same row disagreed with itself.
    rel_frame = info["release_frame"] if info else 0
    rel = info["release_sec"] if info else 0.0
    forced = [g for g in parsed["segments"] if g["start_frame"] < rel_frame]
    after = [g for g in parsed["segments"] if g["start_frame"] >= rel_frame]
    free = [g for g in after if args.count_backchannels or not g["is_backchannel"]]
    said = " ".join(g["text"] for g in free if g["text"]) or None
    audible = free[0]["start"] if free else None

    return {"probe_id": item["probe_id"], "debate_id": item["debate_id"],
            "model": "Raon-SpeechChat-9B",
            # khs_claude_code: both models clone the moderator voice zero shot, so which clip did it
            # belongs in the result rather than only in the run config
            "voice_id": item["voice_id"],
            "ref_wav": str(item["reference_wav"]) if item["reference_wav"] else None,
            "spoke": bool(free), "spoke_at": free[0]["start"] if free else None,
            "audible_at": audible,
            "first_speech_frame": free[0]["start_frame"] if free else None,
            "text": said,
            "segments": free, "n_segments": len(free),
            "prefilled_segments": forced,
            "backchannel_segments": [g for g in after if g["is_backchannel"]],
            "speech_frames": parsed["speech_frames"],
            **window_view(free, item, args.count_backchannels),
            "prefill": info,
            "frame_rate": frame_rate, "n_frames": parsed["n_frames"],
            "assistant_duration_sec": round(summary.get("assistant_duration_sec", 0.0), 3),
            "audio_seconds": round(summary.get("user_duration_sec", 0.0), 3),
            "wav": str((probe_dir / "assistant.wav").relative_to(out_dir)),
            "label": item["label"], "kind": item["kind"],
            "t_earliest": item["t_earliest"], "t_deadline": item["t_deadline"],
            "t_latest": item["t_latest"],
            "elapsed_s": round(time.time() - t0, 2)}


def parse_args():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description=__doc__.splitlines()[0])
    g = ap.add_argument_group("model")
    g.add_argument("--ckpt", required=True, help="official Raon-SpeechChat-9B dir")
    g.add_argument("--dtype", default="bfloat16")
    g.add_argument("--attn", default="sdpa", choices=["sdpa", "eager", "fa"])
    g.add_argument("--decoder-timeout", type=float, default=30.0,
                   help="seconds to wait per frame for the audio decoder subprocess. "
                        "The official value is 1.0, which is too tight on a loaded "
                        "shared node. Waiting longer cannot change what is decoded")
    g.add_argument("--seed", type=int, default=None,
                   help="official decoding samples, so runs differ. Set this to repeat one")
    g.add_argument("--prefill", nargs="?", const="assets/alignments.json", default=None,
                   metavar="ALIGNMENTS",
                   help="put the moderator's earlier turns into the assistant channel "
                        "as if the model had produced them, and feed a moderator free "
                        "input. Needs the word alignments from tools/build_alignments.py")
    g.add_argument("--no-force-audio-codes", dest="force_audio_codes",
                   action="store_false", default=True,
                   help="force only the text and let the model synthesise the history "
                        "itself. Measured over six draws that came out 11 to 94 percent "
                        "voiced, median 43, so it is not the default")
    g.add_argument("--min-voiced", type=float, default=0.5,
                   help="least fraction of the forced history that must come out as "
                        "sound. Below this the draw is discarded and redrawn")
    g.add_argument("--prefill-retries", type=int, default=2,
                   help="redraws allowed before a probe is kept with voiced_ok false")
    g.add_argument("--lookahead-frames", type=int, default=3,
                   help="how many frames before its audio a word's text token is placed. "
                        "3 is the measured median, see tools/measure_text_audio_offset.py")
    g.add_argument("--no-warmup", action="store_true",
                   help="skip the throwaway pass that starts the decoder process")

    g = ap.add_argument_group(
        "sampling. unset means the official config/duplex_infer.yaml value, shown below")
    g.add_argument("--temperature", type=float, default=None)
    g.add_argument("--top-p", type=float, default=None, dest="top_p")
    g.add_argument("--top-k", type=int, default=None, dest="top_k")
    g.add_argument("--sil-penalty", type=float, default=None, dest="sil_penalty",
                   help="raising it makes the model speak sooner and more often, which "
                        "trades the silence probes for the intervention ones")
    g.add_argument("--bc-penalty", type=float, default=None, dest="bc_penalty")
    g.add_argument("--eos-penalty", type=float, default=None, dest="eos_penalty")
    g.add_argument("--speak-first", action="store_const", const=True, default=None,
                   dest="speak_first")

    g = ap.add_argument_group("probe set, all overridable")
    g.add_argument("--data-sample", default=None, help="directory holding the probe set")
    g.add_argument("--probes", default=None)
    g.add_argument("--debates-file", default=None)
    g.add_argument("--system-prompt", default=None, help="prompt template to use instead")
    g.add_argument("--probe-audio", default=None, help="made by make_probe_audio.py")
    g.add_argument("--voices", default=None)
    g.add_argument("--no-reference", action="store_true",
                   help="do not condition on the moderator voice clip")

    g = ap.add_argument_group("selection")
    g.add_argument("--debates", nargs="*", default=None)
    g.add_argument("--probe-ids", nargs="*", default=None)
    g.add_argument("--labels", nargs="*", default=None, help="e.g. A4 A2-1 none")
    g.add_argument("--kinds", nargs="*", default=None,
                   help="clock, event, content, negative")
    g.add_argument("--limit", type=int, default=0, help="pilot on the first N probes")
    g.add_argument("--shard", type=int, default=0)
    g.add_argument("--num-shards", type=int, default=1,
                   help="split the selection across processes, one gpu each. Shards are "
                        "taken round robin so each sees a mix of short and long probes, "
                        "and each writes its own results file")

    g = ap.add_argument_group("output")
    g.add_argument("--out", default="out", help="root for results")
    g.add_argument("--tag", default="default",
                   help="results go to <out>/<tag>, so settings do not collide")
    g.add_argument("--count-backchannels", action="store_true",
                   help="treat a backchannel as an intervention when locating onsets")
    g.add_argument("--keep-stereo", action="store_true",
                   help="keep the official stereo mix, about 14 MB per probe")
    return ap.parse_args()


def main():
    args = parse_args()
    out_dir = pathlib.Path(args.out) / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    results = out_dir / ("results.jsonl" if args.num_shards == 1
                         else f"results.shard{args.shard}.jsonl")

    ps = ProbeSet(args.data_sample, args.probes, args.debates_file,
                  args.system_prompt, args.probe_audio, args.voices)
    missing = ps.missing_audio()
    if missing:
        sys.exit(f"[run] {len(missing)} probe wavs missing under {ps.audio_dir}. "
                 f"Run: cd {ps.root} && python make_probe_audio.py")
    items = ps.items(args.debates, args.probe_ids, args.labels, args.kinds,
                     args.limit, not args.no_reference)
    if args.num_shards > 1:
        items = items[args.shard::args.num_shards]

    sampling = sampling_kwargs(args)
    effective = {**OFFICIAL_DEFAULTS, **sampling}
    (out_dir / "run_config.json").write_text(json.dumps(
        {"model": "Raon-SpeechChat-9B", "args": vars(args),
         "sampling_effective": effective, "sampling_overridden": sampling,
         "probe_set": ps.describe(), "n_selected": len(items),
         "started": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1, default=str))

    done = set()
    if results.exists():
        for line in open(results):
            try:
                done.add(json.loads(line)["probe_id"])
            except Exception:
                continue
    todo = [i for i in items if i["probe_id"] not in done]
    print(f"[run] tag '{args.tag}': {len(items)} probes selected, {len(done)} done, "
          f"{len(todo)} to run  ->  {out_dir}")
    print(f"[run] sampling {effective}"
          + ("" if sampling else "  (all official)"))
    if not todo:
        return

    if args.seed is not None:
        import random
        import numpy as np
        import torch
        random.seed(args.seed)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        torch.cuda.manual_seed_all(args.seed)
        print(f"[run] seed {args.seed}")

    print(f"[run] loading {args.ckpt}")
    from transformers.dynamic_module_utils import get_class_from_dynamic_module
    RaonPipeline = get_class_from_dynamic_module("modeling_raon.RaonPipeline", args.ckpt)
    widen_decoder_timeout(RaonPipeline, args.decoder_timeout)   # khs_claude_code, see the function
    pipe = RaonPipeline(args.ckpt, device="cuda", dtype=args.dtype,
                        attn_implementation=args.attn)
    print(f"[run] pipeline ready, {pipe.processor.frame_rate} frames per second, "
          f"{pipe.processor.sampling_rate} Hz, decoder timeout "
          f"{args.decoder_timeout} s per frame")
    if not args.no_warmup:
        print(f"[run] warm up {warm_up(pipe, out_dir):.1f} s")

    ctl = None
    if args.prefill:
        ap = pathlib.Path(args.prefill)
        if not ap.is_absolute() and not ap.exists():
            ap = pathlib.Path(__file__).resolve().parent / args.prefill
        alignments = prefill.load_alignments(ap)
        for it in todo:
            it["alignments"] = alignments
            it["timeline"] = ps.timeline(it["debate_id"])
        ctl = install_prefill_hook(pipe.model)
        n = len(alignments["turns"])
        print(f"[run] prefill on, {n} aligned turns from {args.prefill}, "
              f"lookahead {args.lookahead_frames} frames "
              f"({args.lookahead_frames * 1000 / pipe.processor.frame_rate:.0f} ms)")

    from tqdm import tqdm
    bar = tqdm(todo, unit="probe", ncols=100, ascii=True, disable=False)
    spoke = 0
    with open(results, "a") as f:
        for item in bar:
            row = run_one(pipe, item, args, out_dir, sampling, ctl)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            spoke += bool(row["spoke"])
            bar.set_postfix(spoke=spoke)
    print(f"[run] {spoke}/{len(todo)} spoke. wrote {results}")


if __name__ == "__main__":
    main()
