#!/usr/bin/env python3
# KHS: proves the environment before any probe is run, and answers the two questions the
# official README leaves open for a speech only benchmark.
#
#   Does the duplex path run with init_vision=False and an empty frame_list?
#     Every duplex example in the README passes video frames. This benchmark has none.
#
#   What does one chunk cost, and does the model's own clock agree with ours?
#     spoke_at is derived from the chunk index, so if streaming_generate reports a
#     current_time that advances by something other than the chunk length, the timing
#     arithmetic in run_probes.py is wrong and must be changed before it is trusted.
"""Verify the MiniCPM-o 4.5 install and measure one duplex chunk.

  python setup/04_verify.py --ckpt ../ckpt/MiniCPM-o-4_5
"""
import argparse
import pathlib
import sys
import time

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--chunks", type=int, default=12)
    ap.add_argument("--chunk-seconds", type=float, default=1.0)
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--attn", default="sdpa")
    ap.add_argument("--with-vision", action="store_true")
    args = ap.parse_args()

    print("[verify] imports")
    import torch
    import transformers
    print(f"  torch        {torch.__version__}  cuda {torch.version.cuda}")
    print(f"  transformers {transformers.__version__}  (official pin is 4.51.0)")
    if not torch.cuda.is_available():
        sys.exit("  no cuda device visible. Set CUDA_VISIBLE_DEVICES.")
    print(f"  gpu          {torch.cuda.get_device_name(0)} "
          f"{torch.cuda.get_device_properties(0).total_memory / 1e9:.0f} GB")
    try:
        import minicpmo
        print(f"  minicpmo     {getattr(minicpmo, '__version__', 'present')}")
    except ImportError:
        sys.exit("  minicpmo not importable. Install minicpmo-utils[all].")

    ckpt = pathlib.Path(args.ckpt).resolve()
    print(f"[verify] checkpoint {ckpt}")
    for f in ("config.json", "modeling_minicpmo.py",
              "assets/token2wav/flow.pt", "assets/token2wav/hift.pt"):
        ok = (ckpt / f).exists()
        print(f"  {'ok  ' if ok else 'MISS'} {f}")
        if not ok:
            sys.exit("  checkpoint incomplete. Rerun 03_download_checkpoint.sh.")

    print(f"[verify] loading (init_vision={args.with_vision})")
    t0 = time.time()
    from transformers import AutoModel
    model = AutoModel.from_pretrained(
        str(ckpt), trust_remote_code=True, attn_implementation=args.attn,
        torch_dtype=getattr(torch, args.dtype),
        init_vision=args.with_vision, init_audio=True, init_tts=True)
    model.eval().cuda()
    model.init_tts()
    duplex = model.as_duplex()
    print(f"  loaded in {time.time() - t0:.0f} s, "
          f"{torch.cuda.max_memory_allocated() / 1e9:.1f} GB allocated")

    print("[verify] one duplex session on silence, no video")
    duplex.prepare(prefix_system_prompt="You moderate a live debate. Usually stay silent.")
    n = int(16000 * args.chunk_seconds)
    times, listens, per_chunk = [], [], []
    for i in range(args.chunks):
        c = np.zeros(n, dtype=np.float32)
        t = time.time()
        duplex.streaming_prefill(audio_waveform=c, frame_list=[],
                                 max_slice_nums=1, batch_vision_feed=False)
        r = duplex.streaming_generate(max_new_speak_tokens_per_chunk=20,
                                      decode_mode="sampling")
        per_chunk.append(time.time() - t)
        listens.append(bool(r.get("is_listen", True)))
        if "current_time" in r:
            times.append(r["current_time"])

    med = sorted(per_chunk)[len(per_chunk) // 2]
    print(f"  chunk cost   median {med:.3f} s for {args.chunk_seconds:.1f} s of audio "
          f"({args.chunk_seconds / med:.1f} x real time)")
    print(f"  is_listen    {sum(listens)}/{len(listens)} chunks listening")
    if times:
        steps = [round(b - a, 3) for a, b in zip(times, times[1:])]
        agree = all(abs(s - args.chunk_seconds) < 1e-2 for s in steps)
        print(f"  current_time steps {sorted(set(steps))} "
              f"{'agrees with chunk length' if agree else 'DISAGREES, fix spoke_at'}")
    else:
        print("  current_time not reported, spoke_at rests on the chunk index alone")

    est = med * 142 * 120 / 3600
    print(f"[verify] rough full run: 142 probes averaging about 120 chunks "
          f"is {est:.1f} h on one gpu if every probe is heard to the end")
    print("[verify] ok")


if __name__ == "__main__":
    main()
