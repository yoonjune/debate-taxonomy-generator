# PersonaPlex / RL-Seamless RunPod CUDA smoke

## 목적과 범위

이 실험은 두 checkpoint가 같은 native runtime과 moderator replay adapter에서 실제로 load·생성되는지
확인한 compatibility smoke다. `data_sample/`은 exposed development data이며, probe가 두 개뿐이므로
accuracy나 우열을 추정하지 않는다.

## 고정 조건

- 날짜: 2026-09-02 (Asia/Seoul)
- GPU: NVIDIA A100-SXM4-80GB 1장
- 관찰된 실행 중 VRAM: 약 20,017 MiB (base positive 실행 중 1회 spot check; peak 측정 아님)
- Python: 3.10.18
- PyTorch: 2.4.1+cu121
- 코드 commit: `4a0012fed171b663e479532c01232e49ee4a5beb`
- runtime commit: NVIDIA PersonaPlex `3428dfd95309a7f3c84fd93259ded0f810d1ff91`
- seed: `42424242`
- teacher forcing: moderator acoustic token only
- base revision: `fdaf4090a61cb315c138a1faee287ffd6c716309`
- RL revision: `3fa800309a4b743a8a6d764253eb45def0334afc`

비교에서 checkpoint 외 input manifest, prompt, reference voice, seed, temperature와 top-k를 고정했다.

## Probe

| probe | gold | release | 평가 구간 | 선택 이유 |
|---|---:|---:|---:|---|
| `L000_p02` | A4 | 33.56s (codec 33.52s) | earliest 36.56s, deadline 38.56s, latest 41.56s | 말해야 하는 positive |
| `L009_p08` | none | 76.42s | silence latest 82.42s, observe end 85.42s | crossfire에서 침묵해야 하는 negative |

## 관찰 결과

| checkpoint | probe | wall time | onset | temporal status | output text after release |
|---|---|---:|---:|---|---|
| base | `L000_p02` | 94.662s | 33.96s | `PREMATURE` | `Right. Right.` |
| base | `L009_p08` | 127.989s | 79.72s | `FALSE_POSITIVE` | `10 seconds. Jackson.` |
| RL-Seamless | `L000_p02` | 126.549s | 34.06s | `PREMATURE` | `Kirsten, Kirsten's got Kirsten says that America's policy creates the demand for the drugs.` |
| RL-Seamless | `L009_p08` | 130.179s | 77.30s | `FALSE_POSITIVE` | `and about how it could be done better. Thank you. That makes sense.` |

`output text`는 모델의 text-token stream이다. 사람이 output audio를 듣고 확정한 transcript가 아니다.
Content judge도 실행하지 않았으므로 네 결과의 semantic status는 `NOT_JUDGED`다.

두 probe만 단순 집계하면 각 checkpoint의 temporal pass는 0/2다. 이것은 smoke의 관찰값이며 모집단
성능 추정치가 아니다.

## Artifact hashes

대용량 WAV와 실행 artifact는 Git에 넣지 않고 RunPod의
`/workspace/debate-taxonomy-generator/baselines/artifacts/runs-smoke-fixed/`에 보존했다.

| checkpoint | probe | output WAV SHA-256 | score JSON SHA-256 |
|---|---|---|---|
| base | `L000_p02` | `80b0de87deae9f84990739f154e2d04608f94c243491e4760f55739892342cb6` | `1caab66803c2fc467dc13cf53162a8c228f694c43951c7a63ee9ea889a81e8b1` |
| base | `L009_p08` | `fd79ad0c6dd40b0407cad536541bca56e82256dd3b2df13831c5c7c5d7cb94d2` | `62b232ab7d4f22922113b0bb953c2fc35847a311910f6e04975be14adfa98921` |
| RL-Seamless | `L000_p02` | `180a82df2c9bf4f368bbd896e473e6d0b112748e1aede056b15b5bdb1156a64f` | `0a6adf0ce3c67a411fe22f5eb068301c012f5af4229f5bbcde0c92a4c3cf2044` |
| RL-Seamless | `L009_p08` | `f91e25eb10e65daa2eef2d5e981b0c9a1f0113ffad87adc735339857f267a551` | `77ac8d0ebd596a2a9a85e418db8af56fd0e31658b12e6e841fb71087e31f5e24` |

같은 seed로 수정 전후 positive를 다시 생성했을 때 두 checkpoint 모두 WAV hash가 같았다.

## 보존한 실패

1. RunPod가 `HF_HUB_ENABLE_HF_TRANSFER=1`을 설정했지만 `hf_transfer`가 없어 첫 download가
   `ValueError`로 중단됐다.
2. pinned upstream package가 voice normalization에 쓰는 `pyloudnorm`을 선언하지 않아 첫 model
   load 이후 `ModuleNotFoundError`가 발생했다.
3. 두 의존성을 `requirements-model-extra.txt`에 고정한 뒤 재실행했다. decoding 설정은 바꾸지
   않았다.

## 해석과 다음 gate

관찰상 두 checkpoint 모두 load·generation compatibility는 통과했다. 그러나 두 모델의 오류가
checkpoint 자체 때문인지, audio-only teacher history와 sampled text history의 불일치 때문인지는 이
실험만으로 분리할 수 없다.

따라서 full 143-probe 실행 전 다음 순서가 필요하다.

1. Qwen3 Forced Aligner로 과거 moderator transcript의 frame-level text-token schedule을 만든다.
2. 동일 probe에서 `audio-only`와 `audio+text` teacher forcing을 비교한다.
3. release 전후 output audio를 사람이 듣고 VAD onset과 boundary artifact를 확인한다.
4. 작은 diagnostic에서 protocol이 안정된 뒤에만 full exposed development batch를 실행한다.
