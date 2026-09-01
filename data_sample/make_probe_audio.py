#!/usr/bin/env python3
"""탐침별 입력 오디오를 만든다.

  python3 make_probe_audio.py

한 탐침 = 파일 하나. 판단 지점까지를 담되,
  · 정답 진행자 발화는 무음으로 지운다 (모델이 그 자리를 채워야 하므로)
  · 마감이 지난 뒤로도 최소 3초는 소리 상황이 이어지게 둔다
  · 창이 끝난 뒤 TAIL 초를 더 재생한다 (파일 길이가 힌트가 되지 않게)

마감 뒤에 무엇이 이어지는가는 탐침 종류에 따라 다르다.
  clock            같은 화자가 계속 말한다. 그대로 두면 된다.
  event / content  진행자가 말하지 않았다면 그 자리는 침묵이었을 것이다.
                   그래서 창 동안 다음 발화를 지운다 — 안 지우면 다음 화자가
                   말을 시작하는 것 자체가 "진행자가 넘겼다"는 답을 알려준다.
"""
import argparse, json
from pathlib import Path
import soundfile as sf

TAIL = 6.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="audio/mix")
    ap.add_argument("--out", default="probe_audio")
    a = ap.parse_args()

    out = Path(a.out); out.mkdir(exist_ok=True)
    P = [json.loads(l) for l in open("probes.jsonl")]
    n = 0
    for p in P:
        did = p["debate_id"]
        src = next(f for f in sorted(Path(a.src).glob(f"{did}.*"))
                   if f.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg"))
        w, sr = sf.read(src, dtype="float32")
        tl = {t["i"]: t for t in json.load(open(f"audio/mix/{did}.json"))["turns"]}

        win_e = p["t_latest"] if p["t_latest"] is not None else p["context_end_sec"] + 3.0
        end = min(win_e + TAIL, len(w) / sr)
        clip = w[:int(end * sr)].copy()

        def silence(t0, t1):
            s, e = int(max(0, t0) * sr), int(min(t1, end) * sr)
            if e > s:
                clip[s:e] = 0.0

        gt = tl[p["before_turn"]]
        silence(gt["start_sec"], gt["end_sec"])          # 정답 진행자 발화

        # 진행자가 침묵했다면 다음 발화도 시작되지 않았을 자리
        if p.get("kind") in ("event", "content"):
            nxt = tl.get(p["before_turn"] + 1)
            if nxt:
                silence(nxt["start_sec"], win_e)

        sf.write(out / f'{p["probe_id"]}.wav', clip, sr)
        n += 1
    print(f"{n}개 -> {out}/   (tail={TAIL}s)")


if __name__ == "__main__":
    main()
