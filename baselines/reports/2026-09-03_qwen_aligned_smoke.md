# Qwen-aligned PersonaPlex / RL-Seamless diagnostic

## 질문과 범위

과거 moderator 음성만 넣던 replay에 해당 발화의 text token도 함께 넣으면, 두 checkpoint에 동일한
대화 이력을 재현할 수 있는가? 또한 이 통제가 두 exposed development probe의 발화 시점에 어떤
변화를 만드는가?

이 실험은 protocol 확인용 2-probe diagnostic이다. accuracy나 checkpoint의 일반적 우열을 추정하지
않으며 semantic content judge와 사람 청취 검수도 아직 수행하지 않았다.

## 입력을 만든 방법

1. Qwen3 ForcedAligner가 각 moderator turn의 대본 단어를 음성 속 시간에 맞췄다.
2. 그 단어를 PersonaPlex tokenizer의 token으로 바꿨다.
3. moderator가 실제로 말한 시각의 12.5 Hz frame에 token을 배치했다.
4. release 전에는 moderator 음성 token과 text token을 모두 강제로 넣고, release 이후에는 모델이
   둘 다 생성하게 했다.
5. codec의 1-frame 지연을 반영해 첫 자유 출력 frame부터 VAD와 생성 text를 평가했다.

Qwen 정렬은 `L000`, `L009` 각각 moderator turn 10/10을 처리했다. `ZERO_DURATION_WORD`가 포함된
turn은 각각 5개와 4개였으며, 원본 timestamp는 보존하고 별도 quality flag와 deterministic frame
packing으로 처리했다. 역순이나 겹침으로 실패한 turn은 없었다.

## 고정 조건

- 날짜: 2026-09-03 (Asia/Seoul)
- GPU: NVIDIA A100-SXM4-80GB 1장
- Python: 3.10.18
- PyTorch: 2.4.1+cu121
- 실행 코드 commit: `ba924146def82f478327445f4cd3b8f9ee36532c`
- seed: `42424242`
- teacher forcing: `agent_audio_text`
- aligner: `Qwen/Qwen3-ForcedAligner-0.6B`
- aligner revision: `c7cbfc2048c462b0d63a45797104fc9db3ad62b7`
- `qwen-asr`: `0.0.6`
- base revision: `fdaf4090a61cb315c138a1faee287ffd6c716309`
- RL revision: `3fa800309a4b743a8a6d764253eb45def0334afc`
- decoding: audio temperature 0.8/top-k 250, text temperature 0.7/top-k 25

## Replay 검증

두 checkpoint가 동일한 tokenizer schedule hash를 사용했고, release 전 반환된 모든 text token을
schedule과 frame 단위로 대조했다.

| probe | 과거 moderator turn | 강제·검증 text frame | dense schedule SHA-256 | 첫 자유 출력 시각 |
|---|---:|---:|---|---:|
| `L000_p02` | 1 | 419/419 | `8505ff03528d373648ac1173ef13eba468f3af6c53fcf03d37adf29f6d2ef6de` | 33.60s |
| `L009_p08` | 4 | 955/955 | `65086c6a513b41d0fa35603958bfb3a5d54375ad0113a29caf6fb947e24b371b` | 76.48s |

codec delay는 두 모델 모두 1 frame(0.08s)이었다. 수정 전 metadata는 출력 frame 번호를 입력 frame
번호로 간주해 경계를 1 frame 일찍 표시했다. 실제 관찰에서는 output frame `f+1`이 schedule frame
`f`와 일치했으며, 수정 후 검증 mismatch는 0건이었다.

## 관찰 결과

| checkpoint | probe | gold | wall time | onset | temporal status | model text after release |
|---|---|---|---:|---:|---|---|
| base | `L000_p02` | A4 | 87.442s | 39.02s | `ON_TIME` | `Alright, thank you Nina. That was very clear. You laid out` |
| base | `L009_p08` | none | 124.971s | 79.70s | `FALSE_POSITIVE` | `Thank you. And Jackson. Jackson argues` |
| RL-Seamless | `L000_p02` | A4 | 136.458s | 33.84s | `PREMATURE` | `Kirsten responds. Kirsten. America has a lot of power.` |
| RL-Seamless | `L009_p08` | none | 125.477s | 79.66s | `FALSE_POSITIVE` | `Jackson argues against Thank you. That completes round two.` |

Base의 positive는 audio-only smoke의 `PREMATURE`에서 `ON_TIME`으로 바뀌었다. 그러나 RL positive는
여전히 `PREMATURE`이고 두 모델의 negative는 모두 `FALSE_POSITIVE`다. text history 통제가 특정
출력에 영향을 준 관찰은 있지만, 2개 probe로 개선이나 checkpoint 우열을 결론낼 수 없다.

## Artifact와 hash

대용량 artifact는 Git에 넣지 않고 RunPod 아래에 보존했다.

- base: `baselines/artifacts/runs-smoke-audio-text-base-fixed/`
- RL-Seamless: `baselines/artifacts/runs-smoke-audio-text-rl-fixed/`
- alignments: `baselines/artifacts/alignments/qwen3-smoke-L000/`, `qwen3-smoke-L009/`

| checkpoint | probe | output WAV SHA-256 | generation JSON SHA-256 | score JSON SHA-256 |
|---|---|---|---|---|
| base | `L000_p02` | `2ba1882fa4eaa297291a38bafdcddc68521775d2f15ad7510a35c6f467774351` | `5fd223c949cbe614c72b15e0bc5a6b538b4500bef4fa0009320539268907b1d6` | `19a515adecd801a85bb08d3a9311dbad41b711e3382d92ee986ee9ec9a201ad1` |
| base | `L009_p08` | `3e42ee205e0fe576f41db4763ab6a89e0b10e8e5e14cc9783fab374c19b8ec84` | `8097faeef5bef11c170a8b033f70e29b59c923372d89e998056e7ba9d8e57f32` | `1eb13f715cfd93f8b8829eb85ac44be2c2ba53dd88da2d7510ca52050757347a` |
| RL-Seamless | `L000_p02` | `ea575a0b5613b9ce0e1ff225b75936f55abfab27be5f95871f799d7d67e77f7b` | `f4733d41183ccb2b4f3b9d27878856f9598cf6e438a625078af8b1c2c9bb80e2` | `efa537b358e7ae6b4b51299f0ef71c307b6f7154a191682243a0d9b7402e2da6` |
| RL-Seamless | `L009_p08` | `8fc693c4f64753d08b22e793fd0d83f621f6ece54b912d90196769e2a000fd9f` | `1f9ab1603f614db53997471ea6c27dcf8c2e41d7f731de7e611f4472bf7ccb2a` | `a23cf0687802055475ac3f67d3704d4e149f797fd6fa1985cd72bd77ae462d14` |

## 남은 validity gate

1. release 전후 audio를 사람이 들어 codec 경계 잡음과 VAD onset을 확인한다.
2. Qwen의 zero-duration warning이 있는 대표 turn의 정렬을 사람이 확인한다.
3. 작은 사전등록 diagnostic subset에서 audio-only와 audio+text 차이를 paired 비교한다.
4. protocol이 안정된 뒤에만 exposed development 전체 batch를 실행한다.

현재 결과는 runtime과 exact text-prefix replay에 대한 `GO`, moderator 성능에 대해서는 `HOLD`다.
