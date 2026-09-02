# Debate Taxonomy Generator

MOD/PRO/CON 3인 토론에서 moderator가 언제, 왜, 어떻게 개입하는지를 9개 taxonomy로 생성하고
검증하는 standalone Codex skill repository다. 각 sample은 **영문 transcript + 한국어 해석 + trigger/action
link + 자동검사 + 의미검사 한계**를 함께 보여준다.

> 현재 공개 범위: 9개 taxonomy의 event-window sample과 validator는 전부 fresh forward test를
> 통과했다. Full-debate는 short A5 smoke test까지 통과했으며, 9개 코드별 full-debate matrix를 모두
> 검증한 상태는 아니다.

## Taxonomy 한눈에 보기

| 코드 | 사람이 읽는 의미 | 눈에 보여야 하는 사건 | 영문·한글 sample |
|---|---|---|---|
| A1 | 시간 초과 강제 종료 | deadline 뒤에도 말하는 화자를 MOD가 끊음 | [A1 sample](evaluation/samples/a1/sample.md) |
| A2-1 | 초과 발화를 끊고 상대에게 넘김 | overrun을 중단하고 상대를 호출, 상대가 다음 발화 | [A2-1 sample](evaluation/samples/a2-1/sample.md) |
| A2-2 | 자연 종료 뒤 상대에게 넘김 | 시간 안에 완결된 뒤 overlap 없이 handoff | [A2-2 sample](evaluation/samples/a2-2/sample.md) |
| A3-1 | 자유토론 시작 | 양측 opening 뒤 Phase 2 direct debate 개시 | [A3-1 sample](evaluation/samples/a3-1/sample.md) |
| A3-2 | 자유토론 종료·마무리 시작 | Phase 2를 닫고 PRO부터 closing 시작 | [A3-2 sample](evaluation/samples/a3-2/sample.md) |
| A4 | 남은 시간 고지 | 8–12초가 남은 floor 위에 MOD가 짧게 안내 | [A4 sample](evaluation/samples/a4/sample.md) |
| A5 | 발언권 보호 | 상대가 floor holder를 가로채고 MOD가 원래 floor 복구 | [A5 sample](evaluation/samples/a5/sample.md) |
| B1 | 논제 이탈 교정 | 실제 곁가지 이탈 뒤 MOD가 motion으로 redirect | [B1 sample](evaluation/samples/b1/sample.md) |
| B2 | 자기모순 지적 | 같은 화자의 양립 불가능한 두 claim 뒤 MOD가 대조 | [B2 sample](evaluation/samples/b2/sample.md) |

정확한 불변조건은 [taxonomy reference](skills/generate-debate-taxonomy/references/taxonomy.md)에 있다.
각 sample 폴더에는 사람이 읽는 `sample.md` 외에도 원본 `sample.json`, `validation.json`,
`semantic_review.json`이 함께 있다.

## 가장 간단한 사용법

이 저장소를 Codex workspace로 연 뒤 project skill의 경로를 함께 지정하면 된다.

```text
skills/generate-debate-taxonomy 스킬을 사용해서 A3-1을 만들어줘.
영문 transcript 아래에 한글 해석도 넣어줘.
```

설치된 skill로 사용하는 환경에서는 다음처럼 호출할 수 있다.

```text
$generate-debate-taxonomy A4 event-window를 만들어줘.
$generate-debate-taxonomy B2가 들어간 short 토론을 만들어줘.
```

Codex skills directory에 설치하려면 다음과 같이 repository를 clone한 뒤
`skills/generate-debate-taxonomy` 폴더를 통째로 복사한다.

```bash
git clone https://github.com/yoonjune/debate-taxonomy-generator.git
cp -R debate-taxonomy-generator/skills/generate-debate-taxonomy \
  <your-codex-skills-directory>/
```

별도 Python package 설치는 필요 없고 Python 3 표준 라이브러리만 사용한다.

위 설명은 taxonomy 생성 skill에 해당한다. `data_sample/`을 PersonaPlex 또는 RL-Seamless에
streaming하고 평가하는 코드는 별도 의존성이 있으며 [baseline README](baselines/README.md)를 따른다.

## Full-duplex moderator baseline

현재 development dataset을 base PersonaPlex와 RL-Seamless에서 동일 조건으로 비교하기 위한 코드가
`baselines/`에 있다.

- participant와 moderator의 두 audio stream 재구성
- probe 전에 ground-truth moderator history teacher forcing
- release 이후 모델 자유 생성
- speech onset의 rule-based timing 평가
- moderator 발화 내용용 judge packet 분리

전체 입력·출력 흐름과 실행 예시는 [baselines/README.md](baselines/README.md), 모델 환경은
[baselines/MODEL_RUNTIME.md](baselines/MODEL_RUNTIME.md)에서 확인할 수 있다.

## 생성 모드

| 모드 | 언제 쓰나 | 시간 표현 | 자동검사 |
|---|---|---|---|
| `event-window` | taxonomy 한 건의 trigger와 MOD action을 선명하게 볼 때 | 실제 `start_sec`/`end_sec` timeline | 코드별 deadline, overlap, phase와 link 검사 |
| `full-debate` | 3-phase short/long 전체 토론이 필요할 때 | voice length-band의 WPM 예상치 | 전체 구조·예상 길이·균형과 일부 taxonomy topology 검사 |

Taxonomy 코드만 요청하면 `event-window`가 기본이다. `short`, `long`, `전체 토론`을 요청하면
`full-debate`를 사용하고 A3-1/A3-2를 자동으로 포함한다.

## 변이를 주는 방법

반복 sample은 이름이나 단어만 바꾸지 않는다. 생성 전에 variation card를 고정해 다음 축을 함께
분산한다.

- domain과 motion family
- trigger subtype
- PRO/CON role pattern
- moderator wording style
- 허용 범위 안의 gap·overlap·개입 시점
- participant set

9개 코드를 한 번씩 배정하는 재현 가능한 plan:

```bash
python3 skills/generate-debate-taxonomy/scripts/plan_variations.py \
  --seed team-demo-001 A1 A2-1 A2-2 A3-1 A3-2 A4 A5 B1 B2
```

같은 taxonomy를 다시 생성할 때는 새 seed와 이전 generation ledger를 사용하고, 이전 exact motion,
motion family, role pattern과 MOD 문구 재사용을 확인한다. Seed는 재현 수단이지 품질 보증이 아니다.

## 자동 검증

개별 event-window:

```bash
python3 skills/generate-debate-taxonomy/scripts/validate_sample.py sample.json
python3 skills/generate-debate-taxonomy/scripts/render_sample.py sample.json > sample.md
```

모든 bundled fixture와 negative regression:

```bash
python3 skills/generate-debate-taxonomy/scripts/validate_examples.py
python3 skills/generate-debate-taxonomy/scripts/test_variation.py
```

생성 batch의 taxonomy coverage와 다양성:

```bash
python3 skills/generate-debate-taxonomy/scripts/validate_batch_diversity.py \
  --expected-csv A1,A2-1,A2-2,A3-1,A3-2,A4,A5,B1,B2 \
  evaluation/samples/*/sample.json
```

Full-debate voice-WPM 예상 길이:

```bash
python3 skills/generate-debate-taxonomy/scripts/validate_full_debate.py \
  evaluation/full_debate_smoke/sample.json
```

## 검증 결과와 해석 범위

| 검사 | 결과 | 의미 |
|---|---:|---|
| Bundled positive fixtures | 9/9 PASS | 각 코드의 machine contract를 만족 |
| Negative regression | 11/11 탐지 | 알려진 잘못된 timing·role·link mutation을 거부 |
| Fresh event-window forward test | 9/9 PASS provisional | 예시를 보지 않은 session이 새 sample 생성 후 자동·transcript-only 검토 통과 |
| Batch diversity | PASS | motion/domain/style/participant가 9/9 unique, 최대 MOD action Jaccard 0.1818 |
| Full-debate | A5 short smoke PASS | voice-WPM 예상 215.050초; 전체 9-code full-debate 검증은 아님 |

자세한 방법과 taxonomy별 결과는 [전체 forward-test 보고서](evaluation/RESULTS_KO.md)에서
확인할 수 있다. B1의 실제 이탈과 B2의 논리적 비양립성은 자동검사만으로 확정하지 않는다. 현재
semantic result는 transcript-only `PASS_PROVISIONAL`이며 human gold, 실제 TTS 품질, benchmark
correctness 또는 배포 성능을 뜻하지 않는다.

## 폴더 구조

```text
skills/generate-debate-taxonomy/
├── SKILL.md                         # Codex workflow
├── agents/openai.yaml               # UI metadata
├── examples/                        # 9개 compact regression fixture
├── references/
│   ├── taxonomy.md                  # 사람이 읽는 taxonomy 계약
│   ├── generation-rules.md          # 생성·timeline·번역 규칙
│   ├── variation.md                 # controlled variation 규칙
│   ├── loop-validation.md           # bounded repair loop
│   ├── contract.json                # event-window machine contract
│   ├── full-debate-contract.json    # short/long machine contract
│   └── default-voice-profiles.json  # timing metadata만 포함
└── scripts/                         # 생성 plan, 검증, rendering

evaluation/
├── RESULTS_KO.md                    # 연구 질문·방법·결과·한계
├── samples/<taxonomy>/              # JSON, bilingual MD, validation, review
├── full_debate_smoke/sample.json    # 재현 가능한 A5 short 입력
└── validation/                      # batch/variation/full-debate smoke 결과
```

Skill 자체 지시는 [SKILL.md](skills/generate-debate-taxonomy/SKILL.md), loop 규칙은
[loop-validation.md](skills/generate-debate-taxonomy/references/loop-validation.md)에 있다.

## 데이터 provenance

공개 sample transcript와 한국어 해석은 합성 데이터이며 개인 대화나 개인정보를 포함하지 않는다.
Bundled voice profile은 오디오나 model weight가 아니라 합성 timing 실험에서 추린 3개 voice ID의
`sec_per_word` metadata만 포함한다. 실제 오디오 합성·청취 평가는 별도 단계다.
