#!/usr/bin/env python3
# khs_claude_code: a short smoke check. It loads the model, runs a few duplex chunks on silence and
# prints what it saw. It is here to catch an install that does not work and to measure
# the per chunk cost before a long run, not to certify anything.
#
# The one number worth looking at is whether the model's own current_time advances by
# the chunk length, because spoke_at is derived from the chunk index. It is reported,
# not enforced.
"""Smoke check the MiniCPM-o 4.5 install.

  python setup/04_smoke.py --ckpt ../ckpt/MiniCPM-o-4_5
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

    import torch
    import transformers
    print(f"[smoke] torch {torch.__version__} cuda {torch.version.cuda}, "
          f"transformers {transformers.__version__}")
    if not torch.cuda.is_available():
        sys.exit("[smoke] no cuda device visible. Set CUDA_VISIBLE_DEVICES.")
    print(f"[smoke] gpu {torch.cuda.get_device_name(0)}")

    ckpt = pathlib.Path(args.ckpt).resolve()
    for f in ("config.json", "modeling_minicpmo.py", "assets/token2wav/flow.pt"):
        if not (ckpt / f).exists():
            sys.exit(f"[smoke] checkpoint missing {f}. Rerun 03_download_checkpoint.sh.")

    print(f"[smoke] loading, init_vision={args.with_vision}")
    t0 = time.time()
    from transformers import AutoModel
    model = AutoModel.from_pretrained(
        str(ckpt), trust_remote_code=True, attn_implementation=args.attn,
        torch_dtype=getattr(torch, args.dtype),
        init_vision=args.with_vision, init_audio=True, init_tts=True)
    model.eval().cuda()
    model.init_tts()
    duplex = model.as_duplex()
    print(f"[smoke] loaded in {time.time() - t0:.0f} s, "
          f"{torch.cuda.max_memory_allocated() / 1e9:.1f} GB")

    duplex.prepare(prefix_system_prompt="You moderate a live debate. "
                                        "Usually remain silent.")
    n = int(16000 * args.chunk_seconds)
    times, listens, cost = [], [], []
    for _ in range(args.chunks):
        t = time.time()
        duplex.streaming_prefill(audio_waveform=np.zeros(n, dtype=np.float32),
                                 frame_list=[], max_slice_nums=1,
                                 batch_vision_feed=False)
        r = duplex.streaming_generate(max_new_speak_tokens_per_chunk=20,
                                      decode_mode="sampling")
        cost.append(time.time() - t)
        listens.append(bool(r.get("is_listen", True)))
        if "current_time" in r:
            times.append(r["current_time"])

    med = sorted(cost)[len(cost) // 2]
    print(f"[smoke] chunk cost median {med:.3f} s for {args.chunk_seconds:.1f} s "
          f"of audio ({args.chunk_seconds / med:.1f} x real time)")
    print(f"[smoke] is_listen {sum(listens)}/{len(listens)} chunks listening")
    if times:
        steps = sorted({round(b - a, 3) for a, b in zip(times, times[1:])})
        print(f"[smoke] current_time steps {steps}, chunk is {args.chunk_seconds}")
    else:
        print("[smoke] current_time not reported, spoke_at rests on the chunk index")
    print(f"[smoke] 143 probes averaging about 120 chunks would be "
          f"{med * 143 * 120 / 3600:.1f} h if every probe ran to the end")


if __name__ == "__main__":
    main()
