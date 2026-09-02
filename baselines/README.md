# PersonaPlex / RL-Seamless moderator baselines

이 폴더는 `data_sample/`의 토론을 full-duplex moderator model에 흘려보내고,
모델이 **말했는지, 언제 말했는지, 무슨 행동을 말했는지**를 분리해 기록한다.

현재 구현 상태:

- 10편·143 probes 데이터 계약 검사
- participant와 moderator의 두 audio stream 재구성
- probe별 teacher-forcing release 계획
- base PersonaPlex와 RL-Seamless가 공유하는 native Moshi adapter
- model-free fixture를 이용한 end-to-end timing regression
- deterministic energy-VAD timing score와 content-judge packet

두 checkpoint의 CUDA runtime smoke는 A100-SXM4 80GB에서 positive 1개와 negative 1개씩
완료했다. 이는 호환성 확인이지 성능 측정이 아니다. 결과와 한계는
[RunPod smoke 보고서](reports/2026-09-02_runpod_smoke.md)에 기록했다.

## 한 probe가 들어가고 나오는 과정

```text
data_sample/debates.jsonl + probes.jsonl + audio/turns/*.mp3
                              │
                              ▼
                    prepare: 두 stream 구성
              ┌────────────────────────────────┐
              │ user.wav                       │
              │   PRO + CON만 원래 시간에 배치 │
              │                                │
              │ agent_teacher.wav              │
              │   MOD만 release 전까지 배치    │
              └────────────────────────────────┘
                              │
             system prompt + moderator reference voice
                              │
                              ▼
              PersonaPlex shared Moshi runtime
              ┌────────────────────────────────┐
 release 전   │ user forced + MOD audio forced │
 release 후   │ user forced + MOD generated    │
              └────────────────────────────────┘
                              │
                              ▼
              output.wav + output_text.json
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
          rule-based timing          content judge packet
          score.json                 judge_packet.json
```

여기서 `agent`는 Codex agent가 아니라 full-duplex 모델의 **출력 화자 stream**을 뜻한다.

## L000 A4의 실제 입력 계약

`L000_p02`는 PRO가 opening을 시작한 뒤 20초에 10초 경고를 해야 하는 probe다.

```text
release                   earliest       deadline        latest
33.56s                    36.56s          38.56s          41.56s
  │ 모델 출력 자유화          │ 너무 이르면 실패  │ 목표 시각          │ 이후 late
  └──────── 3초 관찰 ────────┴───────────────┴──────────────┘
```

release를 deadline보다 먼저 잡기 때문에 모델이 20초 전에 성급하게 말하는 오류도 관찰할 수 있다.
`user.wav`에서는 토론자가 계속 말하고, `agent_teacher.wav`는 33.56초 이후 정확히 무음이다.

## 1. 가벼운 개발 환경

데이터 준비와 score에는 GPU나 Moshi가 필요 없다.

```bash
cd baselines
python3.10 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

저장소 root에서 데이터 계약 확인:

```bash
baselines/.venv/bin/moderator-bench inspect \
  --data-root data_sample
```

특정 probe의 system prompt, release와 정답을 화면에서 확인:

```bash
baselines/.venv/bin/moderator-bench show-probe \
  --data-root data_sample \
  --probe-id L000_p02
```

## 2. 모델 입력 만들기

```bash
baselines/.venv/bin/moderator-bench prepare \
  --data-root data_sample \
  --probe-id L000_p02 \
  --output-dir baselines/artifacts/prepared
```

생성물:

```text
baselines/artifacts/prepared/L000_p02/
├── user.wav                 PRO + CON 입력
├── agent_teacher.wav        release 전 MOD history, 이후 silence
├── system_prompt.txt        debate별 placeholder가 치환된 prompt
└── input_manifest.json      위 파일 hash, release, gold trigger/action/effect
```

`input_manifest.json` 하나만 보면 모델에 무엇이 들어가고 어떤 시간 범위를 평가하는지 확인할 수
있다.

event/content probe에서 정답 moderator 발화 직후의 다음 토론자 발화가 평가 window와 겹치면,
그 겹치는 구간만 `user.wav`에서 무음 처리한다. 모델이 답할 자리를 확보하는 counterfactual
intervention이며, 원본인 것처럼 숨기지 않고 `input.interventions`에 source turn과 시작·종료 시각을
기록한다. 실제 자연 대화 그대로의 별도 평가 track은 CUDA pilot 결과를 본 뒤 추가해야 한다.

여러 probe를 한 번에 준비하면 두 checkpoint가 같은 `batch_input.json`을 공유할 수 있다.

```bash
baselines/.venv/bin/moderator-bench prepare-batch \
  --data-root data_sample \
  --output-dir baselines/artifacts/prepared-dev \
  --limit 10
```

## 3. 모델 없이 전체 흐름 검사

`oracle_tone` fixture는 positive의 deadline에 0.5초 tone을 내고 negative에서는 침묵한다. 모델
성능이 아니라 replay/scorer 배선이 맞는지 확인하는 도구다.

```bash
baselines/.venv/bin/moderator-bench run \
  --input-manifest baselines/artifacts/prepared/L000_p02/input_manifest.json \
  --model-config baselines/configs/models/personaplex_base.json \
  --output-dir baselines/artifacts/runs \
  --fixture oracle_tone

baselines/.venv/bin/moderator-bench score \
  --generation baselines/artifacts/runs/fixture_oracle_tone/L000_p02/generation.json
```

이 regression의 예상 temporal 결과는 `ON_TIME`, onset은 `38.56s`다.

## 4. 실제 PersonaPlex 실행

CUDA 환경 설정은 [MODEL_RUNTIME.md](MODEL_RUNTIME.md)를 따른다. 두 모델은 동일 명령에서 config만
바꾼다.

Base:

```bash
.venv-model/bin/moderator-bench run \
  --input-manifest baselines/artifacts/prepared/L000_p02/input_manifest.json \
  --model-config baselines/configs/models/personaplex_base.json \
  --output-dir baselines/artifacts/runs
```

RL-Seamless:

```bash
.venv-model/bin/moderator-bench run \
  --input-manifest baselines/artifacts/prepared/L000_p02/input_manifest.json \
  --model-config baselines/configs/models/personaplex_rl_seamless.json \
  --output-dir baselines/artifacts/runs
```

checkpoint 외 prompt, voice, release, seed와 decoding 값은 동일하다.

Qwen alignment를 붙인 진단에서는 `prepare`에 `--alignment-index`를 주고 다음 config를 사용한다.

- `personaplex_base_audio_text.json`
- `personaplex_rl_seamless_audio_text.json`

이 모드는 release 이전 MOD 음성뿐 아니라 text stream의 PAD와 PersonaPlex text token도 강제한다.
Qwen의 word timestamp 안에서 여러 SentencePiece token을 배치하는 규칙은 결정론적이지만, 사람이
직접 표시한 frame-level gold는 아니다. 실제 token 배치는 각 run의
`teacher_text_schedule.json`에 보존된다.

배치 실행에서는 checkpoint를 probe마다 다시 읽지 않고 한 번만 load한다.

```bash
.venv-model/bin/moderator-bench run-batch \
  --batch-input baselines/artifacts/prepared-dev/batch_input.json \
  --model-config baselines/configs/models/personaplex_base.json \
  --output-dir baselines/artifacts/runs

.venv-model/bin/moderator-bench run-batch \
  --batch-input baselines/artifacts/prepared-dev/batch_input.json \
  --model-config baselines/configs/models/personaplex_rl_seamless.json \
  --output-dir baselines/artifacts/runs
```

probe 하나가 실패해도 자동 재시도하거나 결과를 버리지 않는다. `batch_run_*.json`에 `ERROR`, 예외
종류와 traceback을 남기고 다음 probe로 진행한다.

## 5. 모델 출력

```text
baselines/artifacts/runs/<model>/<probe_id>/
├── output.wav               teacher prefix + release 이후 생성 audio
├── output_text.json         frame별 text token과 forced 여부
├── teacher_text_schedule.json  audio+text 모드의 강제 token·frame 근거
├── generation.json          model/code/input/output hash와 runtime 정보
├── score.json               speech onset과 temporal 판정
└── judge_packet.json        내용 평가 입력
```

Temporal status:

| status | 뜻 |
|---|---|
| `PREMATURE` | 허용 시작보다 먼저 말함 |
| `ON_TIME` | 허용 window 안에 말함 |
| `LATE` | window 뒤 tail에서 말함 |
| `MISSED` | positive인데 끝까지 침묵 |
| `FALSE_POSITIVE` | silence 정답인데 말함 |
| `CORRECT_SILENCE` | silence 정답을 지킴 |

Positive의 최종 성공은 `ON_TIME`만으로 확정하지 않는다. `judge_packet.json`의 생성 발화가 올바른
taxonomy action인지 별도 판정한 뒤 `joint_pass`를 계산한다.

## 알려진 구현 한계

- `agent_audio_only`는 moderator acoustic token만 강제한다. `agent_audio_text`는 Qwen word
  alignment에서 만든 deterministic text schedule까지 강제한다. 둘을 같은 실험으로 섞지 않는다.
- Energy-VAD threshold는 현재 development 설정이다. 실제 모델 output 몇 편을 사람이 확인한 뒤
  test freeze 전에 고정해야 한다.
- 현재 10편은 exposed development data다.
- 두 checkpoint 모두 pinned NVIDIA runtime에서 load와 생성은 통과했다. 다만 전체 debate 길이의
  batch 안정성은 아직 확인하지 않았다.
- 2-probe smoke에서 두 모델 모두 positive `PREMATURE`, negative `FALSE_POSITIVE`였다. 표본이 너무
  작고 text-state replay가 불완전하므로 모델 성능 결론으로 일반화하지 않는다.
