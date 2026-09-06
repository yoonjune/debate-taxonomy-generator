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
#   3. The loop stops at the first chunk the model chooses to speak in, since that
#      already settles what is measured. --run-to-end keeps going for the full reply.
#
# Everything else is a flag with the official default, and the effective value of every
# flag is written to run_config.json beside the results, so a run can be repeated or
# compared later without reading this file.
"""Run the MiniCPM-o 4.5 full duplex loop over a debate probe set.

  python run_probes.py --ckpt ckpt/MiniCPM-o-4_5 --limit 3
  python run_probes.py --ckpt ckpt/MiniCPM-o-4_5
  python run_probes.py --ckpt ... --tag chunk05 --chunk-seconds 0.5
  python run_probes.py --ckpt ... --tag noref --no-reference --kinds clock
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


def run_one(model, item, args, out_dir):
    import soundfile as sf
    wav = load_audio(item["audio"])
    chunks = to_chunks(wav, args.chunk_seconds)

    ref_path = str(item["reference_wav"]) if item["reference_wav"] else None
    prepare_kwargs = {"prefix_system_prompt": item["system_prompt"]}   # KHS: benchmark prompt
    if ref_path:
        prepare_kwargs["ref_audio"] = load_audio(ref_path)
        prepare_kwargs["prompt_wav_path"] = ref_path
    model.prepare(**prepare_kwargs)

    spoke_at, spoke_chunk, said, speech = None, None, [], []
    t0 = time.time()
    for idx, chunk in enumerate(chunks):
        model.streaming_prefill(audio_waveform=chunk, frame_list=[],   # KHS: no video
                                max_slice_nums=1, batch_vision_feed=False)
        r = model.streaming_generate(prompt_wav_path=ref_path,
                                     max_new_speak_tokens_per_chunk=args.max_speak_tokens,
                                     decode_mode=args.decode_mode)
        if r.get("is_listen", True):
            continue
        if spoke_at is None:
            spoke_chunk = idx
            # the decision is made after hearing chunk idx in full, so the earliest
            # moment sound can leave the model is the end of that chunk
            spoke_at = round((idx + 1) * args.chunk_seconds, 3)
        if r.get("text"):
            said.append(r["text"])
        if r.get("audio_waveform") is not None:
            speech.append(np.asarray(r["audio_waveform"], dtype=np.float32))
        if not args.run_to_end or r.get("end_of_turn"):
            break

    audible_at = None
    if speech and spoke_at is not None:
        merged = np.concatenate(speech)
        audible_at = round(spoke_at + first_sound_offset(merged, args.output_sample_rate), 3)

    row = {"probe_id": item["probe_id"], "debate_id": item["debate_id"],
           "model": "MiniCPM-o-4_5",
           "spoke": spoke_at is not None, "spoke_at": spoke_at,
           "audible_at": audible_at,
           "spoke_chunk": spoke_chunk, "text": "".join(said).strip() or None,
           "chunk_seconds": args.chunk_seconds,
           "n_chunks_heard": (spoke_chunk + 1) if spoke_chunk is not None else len(chunks),
           "audio_seconds": round(len(wav) / SAMPLE_RATE, 3),
           "label": item["label"], "kind": item["kind"],
           "t_earliest": item["t_earliest"], "t_deadline": item["t_deadline"],
           "t_latest": item["t_latest"],
           "elapsed_s": round(time.time() - t0, 2)}
    if speech:
        wav_dir = out_dir / "audio"
        wav_dir.mkdir(parents=True, exist_ok=True)
        p = wav_dir / f'{item["probe_id"]}.wav'
        sf.write(str(p), merged, args.output_sample_rate)
        row["wav"] = str(p.relative_to(out_dir))
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
    g.add_argument("--max-speak-tokens", type=int, default=20)
    g.add_argument("--decode-mode", default="sampling")
    g.add_argument("--run-to-end", action="store_true",
                   help="keep streaming after the model starts speaking, for the whole reply")
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

    g = ap.add_argument_group("output")
    g.add_argument("--out", default="out", help="root for results")
    g.add_argument("--tag", default="default",
                   help="results go to <out>/<tag>, so settings do not collide")
    return ap.parse_args()


def main():
    args = parse_args()
    out_dir = pathlib.Path(args.out) / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    results = out_dir / "results.jsonl"

    ps = ProbeSet(args.data_sample, args.probes, args.debates_file,
                  args.system_prompt, args.probe_audio, args.voices)
    missing = ps.missing_audio()
    if missing:
        sys.exit(f"[run] {len(missing)} probe wavs missing under {ps.audio_dir}. "
                 f"Run: cd {ps.root} && python make_probe_audio.py")
    items = ps.items(args.debates, args.probe_ids, args.labels, args.kinds,
                     args.limit, not args.no_reference)

    # a run describes itself, so a later comparison does not depend on shell history
    (out_dir / "run_config.json").write_text(json.dumps(
        {"model": "MiniCPM-o-4_5", "args": vars(args), "probe_set": ps.describe(),
         "n_selected": len(items),
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

    print(f"[run] loading {args.ckpt}")
    model = build_model(args)
    print("[run] duplex model ready")

    from tqdm import tqdm
    bar = tqdm(todo, unit="probe", ncols=100, ascii=True)
    spoke = 0
    with open(results, "a") as f:
        for item in bar:
            row = run_one(model, item, args, out_dir)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            spoke += bool(row["spoke"])
            bar.set_postfix(spoke=spoke)
    print(f"[run] {spoke}/{len(todo)} spoke. wrote {results}")


if __name__ == "__main__":
    main()
