#!/usr/bin/env python3
# KHS: drives the official MiniCPM-o 4.5 duplex loop over a debate probe set.
#
# The official loop is copied from the repository README, section "Duplex Omni Mode",
# and kept in the same shape: prepare once, then per chunk call streaming_prefill
# followed by streaming_generate. Three things differ from the README example, each
# marked KHS at the line and each forced by the benchmark rather than chosen:
#
#   1. There is no video. The benchmark is speech only, so frame_list is empty and the
#      model is built with init_vision=False.
#   2. The system prompt is the benchmark's moderator instruction.
#   3. The loop stops when the utterance ends rather than running the whole probe,
#      since nothing after the reply is measured. --stop-at-onset stops even earlier,
#      at the first spoken chunk, when only the timing is wanted.
#
# Everything else is a flag with the official default, and the effective value of every
# flag is written to run_config.json beside the results, so a run can be repeated or
# compared later without reading this file.
"""Run the MiniCPM-o 4.5 full duplex loop over a debate probe set.

  python run_probes.py --ckpt ckpt/MiniCPM-o-4_5 --limit 3
  python run_probes.py --ckpt ckpt/MiniCPM-o-4_5
  python run_probes.py --ckpt ... --tag chunk05 --chunk-seconds 0.5
  python run_probes.py --ckpt ... --tag noref --no-reference --kinds clock
  python run_probes.py --ckpt ... --tag fast  --stop-at-onset
"""
import argparse
import json
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from probe_data import ProbeSet                                   # noqa: E402

SAMPLE_RATE = 16000          # the audio encoder's rate, as in the official example

# every knob streaming_generate accepts, with the official default it falls back to.
# listen_prob_scale is the one that changes what this benchmark measures: it scales the
# probability of choosing to listen, so lowering it makes the model speak sooner and
# more often, which trades the silence probes for the intervention ones. It is the
# counterpart of Raon's sil_penalty and is left official for the headline number.
OFFICIAL_DEFAULTS = {"max_new_speak_tokens_per_chunk": 20, "decode_mode": "sampling",
                     "temperature": 0.7, "top_k": 100, "top_p": 0.8,
                     "listen_prob_scale": 1.0, "listen_top_k": None,
                     "text_repetition_penalty": 1.05}


def load_audio(path, sr=SAMPLE_RATE):
    import librosa
    wav, _ = librosa.load(str(path), sr=sr, mono=True)
    return wav.astype(np.float32)


def to_chunks(wav, chunk_seconds):
    """Fixed length chunks, the last one zero padded.

    Padding rather than dropping matters: dropping the remainder would end the stream
    earlier than the probe intends, and the file ending is exactly the cue the probe
    audio is built to hide.
    """
    n = int(SAMPLE_RATE * chunk_seconds)
    return [np.pad(wav[i:i + n], (0, max(0, n - len(wav[i:i + n])))).astype(np.float32)
            for i in range(0, len(wav), n)]


def first_sound_offset(wav, sr, floor=0.02, win_ms=20.0, sustain=3):
    """Seconds from the start of a waveform until sound is sustained.

    spoke_at is when the model DECIDED to speak. What a listener hears can be later,
    because generated speech can open with silence, and the scoring window is only a
    few seconds wide, so the difference is not negligible. This measures it from the
    audio itself. Onset must hold for `sustain` windows so a single click does not
    count as the start of the utterance.
    """
    n = max(1, int(sr * win_ms / 1000))
    m = len(wav) // n
    if m == 0:
        return 0.0
    rms = np.sqrt((wav[:m * n].reshape(m, n).astype(np.float64) ** 2).mean(axis=1))
    peak = float(rms.max()) if len(rms) else 0.0
    if peak <= 0:
        return 0.0
    hot = rms > max(floor * peak, 1e-5)
    run = np.convolve(hot.astype(np.int32), np.ones(sustain, dtype=np.int32), "valid")
    idx = np.where(run == sustain)[0]
    return float(idx[0]) * n / sr if len(idx) else 0.0


def generation_kwargs(args):
    """Only the knobs actually set on the command line, so the rest stay official."""
    out = {}
    for k in OFFICIAL_DEFAULTS:
        v = getattr(args, k, None)
        if v is not None:
            out[k] = v
    return out


def build_model(args):
    import torch
    from transformers import AutoModel
    model = AutoModel.from_pretrained(
        str(args.ckpt), trust_remote_code=True, attn_implementation=args.attn,
        torch_dtype=getattr(torch, args.dtype),
        init_vision=args.with_vision,     # KHS: speech only benchmark, no video stream
        init_audio=True, init_tts=True)
    model.eval().cuda()
    model.init_tts()
    return model.as_duplex()


def window_view(segments, item):
    """Where the model's onsets fall relative to the scoring window.

    Not a score, just the arithmetic a reader would otherwise redo, and it is here
    because a full duplex model speaks more than once in one probe. The first onset is
    often not the interesting one.

      onset_in_window  the first onset inside [t_earliest, t_latest], or None
      nearest_onset    the onset closest to t_deadline, in window or not
      onset_offset     nearest_onset minus t_deadline, so the sign says early or late
    """
    lo, hi, dl = item["t_earliest"], item["t_latest"], item["t_deadline"]
    out = {"onset_in_window": None, "nearest_onset": None, "onset_offset": None}
    if dl is None or not segments:
        return out
    for seg in segments:
        if lo is not None and hi is not None and lo <= seg["start"] <= hi:
            out["onset_in_window"] = seg["start"]
            break
    near = min(segments, key=lambda x: abs(x["start"] - dl))
    out["nearest_onset"] = near["start"]
    out["onset_offset"] = round(near["start"] - dl, 3)
    return out


def run_one(model, item, args, out_dir, gen):
    """One probe.

    KHS: the whole probe is streamed and EVERY stretch of speech is recorded, not only
    the first. A full duplex model speaks more than once: on this data both models open
    by announcing the debate format, because the system prompt says to do that at the
    start and every probe begins in the middle of a debate where it was already
    announced. Reporting only the first onset would hide a correct intervention thirty
    seconds later and score the model on its opening line instead. --stop-at-onset takes
    the old cheap path when only a first timestamp is wanted.
    """
    import soundfile as sf
    wav = load_audio(item["audio"])
    chunks = to_chunks(wav, args.chunk_seconds)

    ref_path = str(item["reference_wav"]) if item["reference_wav"] else None
    prepare_kwargs = {"prefix_system_prompt": item["system_prompt"]}   # KHS: benchmark prompt
    if ref_path:
        prepare_kwargs["ref_audio"] = load_audio(ref_path)
        prepare_kwargs["prompt_wav_path"] = ref_path
    model.prepare(**prepare_kwargs)

    segments, cur, speech = [], None, []
    t0 = time.time()
    for idx, chunk in enumerate(chunks):
        model.streaming_prefill(audio_waveform=chunk, frame_list=[],   # KHS: no video
                                max_slice_nums=1, batch_vision_feed=False)
        r = model.streaming_generate(prompt_wav_path=ref_path, **gen)
        listening = r.get("is_listen", True)
        if listening:
            if cur is not None:
                segments.append(cur)
                cur = None
            continue
        if cur is None:
            # the decision is made after hearing chunk idx in full, so the earliest
            # moment sound can leave the model is the end of that chunk
            cur = {"start": round((idx + 1) * args.chunk_seconds, 3),
                   "start_chunk": idx, "end_chunk": idx, "text": "",
                   "audio_start": sum(len(a) for a in speech)}
        cur["end_chunk"] = idx
        cur["end"] = round((idx + 2) * args.chunk_seconds, 3)
        if r.get("text"):
            cur["text"] += r["text"]
        if r.get("audio_waveform") is not None:
            speech.append(np.asarray(r["audio_waveform"], dtype=np.float32))
        if args.stop_at_onset:
            break
        if cur["end_chunk"] - cur["start_chunk"] + 1 >= args.max_speak_chunks:
            segments.append(cur)
            cur = None
    if cur is not None:
        segments.append(cur)
    for seg in segments:
        seg["text"] = seg["text"].strip() or None
        seg["duration"] = round(seg["end"] - seg["start"], 3)
        seg.pop("audio_start", None)

    merged = np.concatenate(speech) if speech else None
    audible_at = None
    if merged is not None and segments:
        audible_at = round(segments[0]["start"]
                           + first_sound_offset(merged, args.output_sample_rate), 3)

    row = {"probe_id": item["probe_id"], "debate_id": item["debate_id"],
           "model": "MiniCPM-o-4_5",
           "spoke": bool(segments),
           "spoke_at": segments[0]["start"] if segments else None,
           "audible_at": audible_at,
           "text": " ".join(s["text"] for s in segments if s["text"]) or None,
           "segments": segments, "n_segments": len(segments),
           **window_view(segments, item),
           "chunk_seconds": args.chunk_seconds,
           "n_chunks": len(chunks),
           "audio_seconds": round(len(wav) / SAMPLE_RATE, 3),
           "label": item["label"], "kind": item["kind"],
           "t_earliest": item["t_earliest"], "t_deadline": item["t_deadline"],
           "t_latest": item["t_latest"],
           "elapsed_s": round(time.time() - t0, 2)}
    if merged is not None:
        wav_dir = out_dir / "audio"
        wav_dir.mkdir(parents=True, exist_ok=True)
        q = wav_dir / f'{item["probe_id"]}.wav'
        sf.write(str(q), merged, args.output_sample_rate)
        row["wav"] = str(q.relative_to(out_dir))
    return row


def parse_args():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description=__doc__.splitlines()[0])
    g = ap.add_argument_group("model")
    g.add_argument("--ckpt", required=True, help="official MiniCPM-o 4.5 checkpoint dir")
    g.add_argument("--dtype", default="bfloat16")
    g.add_argument("--attn", default="sdpa", choices=["sdpa", "flash_attention_2"])
    g.add_argument("--with-vision", action="store_true",
                   help="build the vision tower too, if the duplex path needs it")

    g = ap.add_argument_group("decoding, official defaults")
    g.add_argument("--chunk-seconds", type=float, default=1.0,
                   help="audio per step, and so the resolution of spoke_at")
    g.add_argument("--max-new-speak-tokens-per-chunk", type=int, default=None)
    g.add_argument("--decode-mode", default=None, help="official is sampling")
    g.add_argument("--temperature", type=float, default=None)
    g.add_argument("--top-k", type=int, default=None, dest="top_k")
    g.add_argument("--top-p", type=float, default=None, dest="top_p")
    g.add_argument("--listen-prob-scale", type=float, default=None,
                   dest="listen_prob_scale",
                   help="scales the probability of choosing to listen. Below 1.0 the "
                        "model speaks sooner and more often, which trades the silence "
                        "probes for the intervention ones")
    g.add_argument("--listen-top-k", type=int, default=None, dest="listen_top_k")
    g.add_argument("--text-repetition-penalty", type=float, default=None,
                   dest="text_repetition_penalty")
    g.add_argument("--seed", type=int, default=None,
                   help="official decoding samples, so runs differ. Set this to repeat one")
    g.add_argument("--stop-at-onset", action="store_true",
                   help="stop at the first spoken chunk. Timing is already settled "
                        "there, so this is the cheap path when the reply text is not "
                        "wanted. Default is to capture the whole utterance")
    g.add_argument("--max-speak-chunks", type=int, default=30,
                   help="cap on how long one reply may run")
    g.add_argument("--output-sample-rate", type=int, default=24000)

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

    # a run describes itself, so a later comparison does not depend on shell history
    gen = generation_kwargs(args)
    (out_dir / "run_config.json").write_text(json.dumps(
        {"model": "MiniCPM-o-4_5", "args": vars(args), "probe_set": ps.describe(),
         "generation_effective": {**OFFICIAL_DEFAULTS, **gen},
         "generation_overridden": gen, "n_selected": len(items),
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
    if not todo:
        return

    print(f"[run] generation {dict(OFFICIAL_DEFAULTS, **gen)}"
          + ("" if gen else "  (all official)"))
    if args.seed is not None:
        import random
        import torch
        random.seed(args.seed)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        torch.cuda.manual_seed_all(args.seed)
        print(f"[run] seed {args.seed}")

    print(f"[run] loading {args.ckpt}")
    model = build_model(args)
    print("[run] duplex model ready")

    from tqdm import tqdm
    bar = tqdm(todo, unit="probe", ncols=100, ascii=True)
    spoke = 0
    with open(results, "a") as f:
        for item in bar:
            row = run_one(model, item, args, out_dir, gen)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            spoke += bool(row["spoke"])
            bar.set_postfix(spoke=spoke)
    print(f"[run] {spoke}/{len(todo)} spoke. wrote {results}")


if __name__ == "__main__":
    main()
