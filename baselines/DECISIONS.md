# Baseline decision log

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
