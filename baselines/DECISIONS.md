# Baseline decision log

## 2026-09-03 — aligned text replay GO, moderator performance HOLD

### 관찰

- Qwen3 ForcedAligner가 `L000`, `L009`의 moderator turn을 각각 10/10 정렬했다.
- base와 RL-Seamless 모두 동일 dense schedule을 사용했고, release 전 반환 text token이
  `L000_p02` 419/419 frame, `L009_p08` 955/955 frame에서 schedule과 일치했다.
- PersonaPlex codec은 schedule 입력보다 출력을 1 frame(0.08s) 늦게 반환했다. 이 지연을 반영해
  평가를 다시 실행했다.
- 2-probe 결과는 base가 `ON_TIME`/`FALSE_POSITIVE`, RL-Seamless가
  `PREMATURE`/`FALSE_POSITIVE`였다.

### 결정

- Qwen-aligned `agent_audio_text` replay 구현과 frame-level prefix 검증은 runtime gate를 통과했다.
- full exposed development batch와 moderator 성능 판단은 계속 `HOLD`한다.
- 다음 gate는 release 경계와 zero-duration 정렬의 human listening/inspection, 그리고 작은 고정
  subset의 paired audio-only 대 audio+text diagnostic이다.
- codec delay를 제외하지 않은 과거 score는 새 score와 섞지 않는다.

### 이유

동일 schedule을 실제 반환 token과 대조했으므로 과거 moderator text state가 두 checkpoint에 같은
방식으로 입력됐다는 것은 확인했다. 하지만 2개 exposed probe 중 negative 오류는 남았고 content를
사람이 검수하지 않았으므로 성능 개선이나 checkpoint 우열의 근거로 사용할 수 없다.

### 근거

- 코드: `ba924146def82f478327445f4cd3b8f9ee36532c`
- 상세 조건과 artifact hash: `reports/2026-09-03_qwen_aligned_smoke.md`

## 2026-09-02 — Qwen zero-duration word policy

### 관찰

- pinned Qwen3 ForcedAligner로 `L000` turn 0을 정렬했을 때 53개 단어 중 `a` 하나가
  `12.400–12.400s`를 받았다.
- 앞 단어 `gets`는 12.400s에 끝나고 다음 단어 `thirtysecond`도 12.400s에 시작해, 순서는
  단조롭지만 해당 단어만 지속시간이 0이었다.

### 결정

- Qwen 원본 timestamp는 수정하지 않는다.
- `ZERO_DURATION_WORD`는 warning으로 보존하고 해당 경계 시각을 token의 desired time으로 쓴다.
- 여러 token이 같은 frame을 요구하면 모든 발화에 공통인 deterministic unique-frame packing을
  적용하고, desired time과 실제 frame을 모두 schedule artifact에 기록한다.
- 역순 또는 겹치는 word span은 계속 fatal로 처리한다.

### 이유

한 단어의 0초 span 때문에 전체 turn을 버리면 현재 실제 Qwen 출력으로 diagnostic을 진행할 수
없다. 반대로 timestamp 자체를 임의로 늘리면 원본과 파생값이 섞인다. 경계 시각을 보존하고
PersonaPlex의 한-frame-one-token 제약을 별도의 추적 가능한 packing 단계에서 처리하면 두 정보를
구분할 수 있다.

## 2026-09-02 — CUDA runtime GO, evaluation validity HOLD

### 관찰

- base PersonaPlex와 RL-Seamless가 동일한 pinned NVIDIA runtime에서 각각 두 probe의 CUDA 생성을
  완료했다.
- 두 모델 모두 A4 positive에서 `PREMATURE`, crossfire negative에서 `FALSE_POSITIVE`였다.
- 실행 중 v0.1은 과거 moderator acoustic token만 강제하고 병렬 text token은 sampling한다.

### 결정

- 두 checkpoint의 runtime compatibility gate는 `GO`다.
- 현재 결과는 exposed development runtime smoke로만 보존한다.
- full 143-probe 결과를 definitive baseline으로 산출하는 것은 `HOLD`한다.
- 다음 gate는 Qwen3 Forced Aligner 기반 moderator text-token schedule을 추가한 소규모 diagnostic과
  release 경계 음성의 human listening이다.
- audio-only replay를 계속 쓸 경우 exact replay와 섞지 않고 별도 ablation 이름으로 보고한다.

### 이유

두 probe 결과만으로 checkpoint 성능을 일반화할 수 없고, acoustic history와 sampled text history의
불일치가 release 이후 행동에 영향을 줄 수 있다. 이 요인을 통제하기 전에 전체 배치를 돌리면 모델
문제와 replay protocol 문제를 분리할 수 없다.

### 근거

- 코드: `4a0012fed171b663e479532c01232e49ee4a5beb`
- 상세 조건과 artifact hash: `reports/2026-09-02_runpod_smoke.md`
