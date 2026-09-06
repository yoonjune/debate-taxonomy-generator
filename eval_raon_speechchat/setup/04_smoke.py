#!/usr/bin/env python3
# KHS: a short smoke check. It loads the pipeline, runs one duplex pass on a few seconds
# of silence and prints what it saw. It is here to catch an install that does not work
# and to measure the speed before a long run, not to certify anything.
#
# The one number worth looking at is whether the frame count matches the audio length
# times the frame rate, because spoke_at is the first SPEECH frame divided by that rate.
# It is reported, not enforced.
"""Smoke check the Raon-SpeechChat install.

  python setup/04_smoke.py --ckpt ../ckpt/Raon-SpeechChat-9B
"""
import argparse
import pathlib
import sys
import tempfile
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--attn", default="sdpa")
    args = ap.parse_args()

    import numpy as np
    import torch
    import transformers
    print(f"[smoke] torch {torch.__version__} cuda {torch.version.cuda}, "
          f"transformers {transformers.__version__}")
    if not torch.cuda.is_available():
        sys.exit("[smoke] no cuda device visible. Set CUDA_VISIBLE_DEVICES.")
    print(f"[smoke] gpu {torch.cuda.get_device_name(0)}")
    try:
        import speechbrain                                     # noqa: F401
    except ImportError:
        print("[smoke] speechbrain missing, speaker conditioning will fail")

    ckpt = pathlib.Path(args.ckpt).resolve()
    for f in ("config.json", "modeling_raon.py", "model.safetensors.index.json"):
        if not (ckpt / f).exists():
            sys.exit(f"[smoke] checkpoint missing {f}. Rerun 03_download_checkpoint.sh.")

    print("[smoke] loading pipeline")
    t0 = time.time()
    from transformers.dynamic_module_utils import get_class_from_dynamic_module
    RaonPipeline = get_class_from_dynamic_module("modeling_raon.RaonPipeline", str(ckpt))
    pipe = RaonPipeline(str(ckpt), device="cuda", dtype=args.dtype,
                        attn_implementation=args.attn)
    sr, fr = int(pipe.processor.sampling_rate), float(pipe.processor.frame_rate)
    print(f"[smoke] loaded in {time.time() - t0:.0f} s, "
          f"{torch.cuda.max_memory_allocated() / 1e9:.1f} GB")
    print(f"[smoke] {sr} Hz, {fr} fps, {1000.0 / fr:.0f} ms per frame")

    import soundfile as sf
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        wav = td / "silence.wav"
        sf.write(str(wav), np.zeros(int(sr * args.seconds), dtype="float32"), sr)
        t0 = time.time()
        summary = pipe.duplex(audio_input=pipe.load_audio(str(wav)),
                              output_dir=str(td / "out"),
                              system_prompt="You moderate a live debate. "
                                            "Usually remain silent.")
        elapsed = time.time() - t0
        log = (td / "out" / "frame_log.txt").read_text().splitlines()

    n = len([l for l in log if l.startswith("[")])
    speech = len([l for l in log if l.startswith("[SPEECH]")])
    print(f"[smoke] frames {n}, expected about {int(args.seconds * fr)}")
    print(f"[smoke] phases {n - speech} SIL, {speech} SPEECH, "
          f"assistant {summary.get('assistant_duration_sec', 0):.2f} s")
    rt = args.seconds / elapsed
    print(f"[smoke] speed {elapsed:.1f} s wall for {args.seconds:.0f} s "
          f"({rt:.2f} x real time)")
    print(f"[smoke] 143 probes averaging about 150 s of audio would be "
          f"{143 * 150.0 / rt / 3600:.1f} h")


if __name__ == "__main__":
    main()
