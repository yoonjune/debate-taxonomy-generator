#!/usr/bin/env python3
# KHS: proves the environment before any probe is run, and pins down the one number the
# whole timing result rests on.
#
#   What is the frame rate, and does the frame log agree with it?
#     spoke_at is the first SPEECH frame divided by the frame rate. The checkpoint
#     config says 12.5 frames per second, but this reads it from the processor and then
#     checks it against a real run: the number of frames the log holds must match the
#     length of the input audio times the frame rate. If it does not, every timestamp
#     this branch produces is scaled wrong and nothing should be run until it is fixed.
"""Verify the Raon-SpeechChat install and check the frame clock.

  python setup/04_verify.py --ckpt ../ckpt/Raon-SpeechChat-9B
"""
import argparse
import pathlib
import sys
import tempfile
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--seconds", type=float, default=10.0,
                    help="length of the silent probe used for the timing check")
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--attn", default="sdpa")
    args = ap.parse_args()

    print("[verify] imports")
    import numpy as np
    import torch
    import transformers
    print(f"  torch        {torch.__version__}  cuda {torch.version.cuda}")
    print(f"  transformers {transformers.__version__}  (official floor is 4.57.1)")
    if not torch.cuda.is_available():
        sys.exit("  no cuda device visible. Set CUDA_VISIBLE_DEVICES.")
    print(f"  gpu          {torch.cuda.get_device_name(0)} "
          f"{torch.cuda.get_device_properties(0).total_memory / 1e9:.0f} GB")
    try:
        import speechbrain                                     # noqa: F401
        print("  speechbrain  present, speaker conditioning available")
    except ImportError:
        print("  speechbrain  MISSING, speaker_audio conditioning will fail")

    ckpt = pathlib.Path(args.ckpt).resolve()
    print(f"[verify] checkpoint {ckpt}")
    for f in ("config.json", "modeling_raon.py", "model.safetensors.index.json"):
        ok = (ckpt / f).exists()
        print(f"  {'ok  ' if ok else 'MISS'} {f}")
        if not ok:
            sys.exit("  checkpoint incomplete. Rerun 03_download_checkpoint.sh.")

    print("[verify] loading pipeline")
    t0 = time.time()
    from transformers.dynamic_module_utils import get_class_from_dynamic_module
    RaonPipeline = get_class_from_dynamic_module("modeling_raon.RaonPipeline", str(ckpt))
    pipe = RaonPipeline(str(ckpt), device="cuda", dtype=args.dtype,
                        attn_implementation=args.attn)
    sr = int(pipe.processor.sampling_rate)
    fr = float(pipe.processor.frame_rate)
    print(f"  loaded in {time.time() - t0:.0f} s, "
          f"{torch.cuda.max_memory_allocated() / 1e9:.1f} GB allocated")
    print(f"  sampling rate {sr} Hz, frame rate {fr} fps, "
          f"{1000.0 / fr:.0f} ms per frame")

    print(f"[verify] one duplex run on {args.seconds:.0f} s of silence")
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
    expect = int(args.seconds * fr)
    ok = abs(n - expect) <= 1
    print(f"  frames written {n}, expected about {expect} "
          f"{'agrees with the frame rate' if ok else 'DISAGREES, fix spoke_at'}")
    speech = [l for l in log if l.startswith("[SPEECH]")]
    print(f"  phases         {n - len(speech)} SIL, {len(speech)} SPEECH")
    print(f"  assistant      {summary.get('assistant_duration_sec', 0):.2f} s of audio")
    print(f"  speed          {elapsed:.1f} s wall for {args.seconds:.0f} s of audio "
          f"({args.seconds / elapsed:.2f} x real time)")
    est = 142 * 150.0 / (args.seconds / elapsed) / 3600
    print(f"[verify] rough full run: 142 probes averaging about 150 s of audio "
          f"is {est:.1f} h on one gpu")
    if not ok:
        sys.exit("[verify] frame clock disagrees, do not run probes yet")
    print("[verify] ok")


if __name__ == "__main__":
    main()
