#!/usr/bin/env python3
# KHS: drives the official MiniCPM-o 4.5 duplex loop over the debate probes.
#
# The official loop is copied from the repository README, section "Duplex Omni Mode",
# and kept in the same shape on purpose: prepare once, then per chunk call
# streaming_prefill followed by streaming_generate. Three things differ from the README
# example, each marked KHS below and each forced by the benchmark rather than chosen:
#
#   1. There is no video. The benchmark is speech only, so frame_list is empty and the
#      model is built with init_vision=False.
#   2. The system prompt is the benchmark's moderator instruction with its four
#      placeholders substituted, not the example's "Streaming Omni Conversation.".
#   3. The loop stops at the first chunk the model chooses to speak in. What this
#      benchmark measures is WHEN it decides to speak, so once is_listen turns false the
#      answer is already determined and the remaining chunks would only cost time.
#      Pass --run-to-end to keep going and capture the full reply instead.
#
# Timing. is_listen is reported once per chunk, so the resolution of spoke_at is the
# chunk length. The scoring window in probes.jsonl is t_deadline minus 2.0 to
# t_deadline plus 3.0, five seconds wide, so a one second chunk sits well inside it, but
# the chunk index is recorded alongside so any reader can redo the arithmetic.
"""Run the MiniCPM-o 4.5 full duplex loop over data_sample probes.

  python run_probes.py --ckpt ckpt/MiniCPM-o-4_5 --out out/minicpm_o_4_5
  python run_probes.py --ckpt ... --limit 3            # short pilot first
  python run_probes.py --ckpt ... --debates L000 L001  # one or two debates
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
    out = []
    for i in range(0, len(wav), n):
        c = wav[i:i + n]
        if len(c) < n:
            c = np.pad(c, (0, n - len(c)))
        out.append(c.astype(np.float32))
    return out


def build_model(ckpt, dtype, attn, with_vision):
    import torch
    from transformers import AutoModel
    model = AutoModel.from_pretrained(
        str(ckpt),
        trust_remote_code=True,
        attn_implementation=attn,
        torch_dtype=getattr(torch, dtype),
        init_vision=with_vision,     # KHS: speech only benchmark, no video stream
        init_audio=True,
        init_tts=True,
    )
    model.eval().cuda()
    model.init_tts()
    return model.as_duplex()


def run_one(model, item, args, out_dir):
    """One probe. Returns the result row."""
    import soundfile as sf
    wav = load_audio(item["audio"])
    chunks = to_chunks(wav, args.chunk_seconds)

    ref_path = str(item["reference_wav"]) if item["reference_wav"] else None
    ref_audio = load_audio(ref_path) if ref_path else None
    prepare_kwargs = {"prefix_system_prompt": item["system_prompt"]}   # KHS: benchmark prompt
    if ref_audio is not None:
        prepare_kwargs["ref_audio"] = ref_audio
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
        if not args.run_to_end:
            break
        if r.get("end_of_turn"):
            break

    row = {
        "probe_id": item["probe_id"],
        "debate_id": item["debate_id"],
        "model": "MiniCPM-o-4_5",
        "spoke": spoke_at is not None,
        "spoke_at": spoke_at,
        "spoke_chunk": spoke_chunk,
        "text": "".join(said).strip() or None,
        "chunk_seconds": args.chunk_seconds,
        "n_chunks_heard": (spoke_chunk + 1) if spoke_chunk is not None else len(chunks),
        "audio_seconds": round(len(wav) / SAMPLE_RATE, 3),
        "label": item["label"],
        "kind": item["kind"],
        "t_earliest": item["t_earliest"],
        "t_deadline": item["t_deadline"],
        "t_latest": item["t_latest"],
        "elapsed_s": round(time.time() - t0, 2),
    }
    if speech:
        wav_dir = out_dir / "audio"
        wav_dir.mkdir(parents=True, exist_ok=True)
        p = wav_dir / f'{item["probe_id"]}.wav'
        sf.write(str(p), np.concatenate(speech), args.output_sample_rate)
        row["wav"] = str(p.relative_to(out_dir))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True, help="official MiniCPM-o 4.5 checkpoint dir")
    ap.add_argument("--out", default="out/minicpm_o_4_5")
    ap.add_argument("--data-sample", default=None)
    ap.add_argument("--probe-audio", default=None,
                    help="default data_sample/probe_audio, made by make_probe_audio.py")
    ap.add_argument("--debates", nargs="*", default=None)
    ap.add_argument("--limit", type=int, default=0, help="pilot on the first N probes")
    ap.add_argument("--chunk-seconds", type=float, default=1.0)
    ap.add_argument("--max-speak-tokens", type=int, default=20)
    ap.add_argument("--decode-mode", default="sampling")
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--attn", default="sdpa", choices=["sdpa", "flash_attention_2"])
    ap.add_argument("--with-vision", action="store_true",
                    help="build the vision tower too, for the case where the duplex "
                         "path refuses to run without it")
    ap.add_argument("--run-to-end", action="store_true",
                    help="keep streaming after the model starts speaking, to capture "
                         "the whole reply instead of only its start time")
    ap.add_argument("--output-sample-rate", type=int, default=24000)
    args = ap.parse_args()

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = out_dir / "results.jsonl"

    ps = ProbeSet(args.data_sample, args.probe_audio)
    missing = ps.missing_audio()
    if missing:
        sys.exit(f"[run] {len(missing)} probe wavs missing under {ps.audio_dir}. "
                 f"Run: cd {ps.root} && python make_probe_audio.py")
    items = ps.items(args.debates, args.limit)

    done = set()
    if results.exists():
        for line in open(results):
            try:
                done.add(json.loads(line)["probe_id"])
            except Exception:
                continue
    todo = [i for i in items if i["probe_id"] not in done]
    print(f"[run] {len(items)} probes selected, {len(done)} already done, "
          f"{len(todo)} to run")
    if not todo:
        return

    print(f"[run] loading {args.ckpt}")
    model = build_model(args.ckpt, args.dtype, args.attn, args.with_vision)
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
    print(f"[run] wrote {results}")


if __name__ == "__main__":
    main()
