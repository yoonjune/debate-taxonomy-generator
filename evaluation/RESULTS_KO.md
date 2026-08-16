# Debate taxonomy skill 전체 forward test

검사일: 2026-08-16
검사 대상: `skills/generate-debate-taxonomy`
모델: GPT-5.6 Luna fresh session 9개

## 연구 질문

예시 정답을 보지 않은 fresh session이 project skill과 사전 배정된 variation card만으로 A1부터
B2까지 각 taxonomy의 event-window를 생성하고, 자동검사와 transcript-only 의미검사를 통과할 수
있는지 확인했다.

이는 sample-level forward test다. Human validation, 실제 음성 합성, benchmark correctness 또는
배포 성능을 검증한 것이 아니다.

## 방법

- Taxonomy마다 별도 fresh Luna session을 사용했다.
- Agent는 `examples/`, example catalog, 과거 forward-test 결과와 다른 agent 출력을 읽지 않았다.
- Batch 생성 전에 seed `forward-all-20260816`으로 9개 variation card를 고정했다.
- Card는 domain, motion family, trigger subtype, role pattern, MOD style, timing profile과 participant
  set을 포함한다.
- Agent는 `sample.json`, 영문·한글 `sample.md`, `validation.json`, `semantic_review.json`을 만들었다.
- Root session이 모든 JSON에 validator와 variation-alignment 검사를 다시 실행했다.
- 실패 시 taxonomy, motion, roles, card와 threshold는 고정하고 bounded local repair만 허용했다.

## Taxonomy별 결과

| Taxonomy | Motion domain | 자동검사 | Transcript-only 의미검사 | 최대 WPM | 관찰된 repair |
|---|---|---|---|---:|---|
| A1 | energy | PASS | PASS provisional | 247.059 | timing 1회 |
| A2-1 | science | PASS | PASS provisional | 257.143 | timing 1회 |
| A2-2 | culture | PASS | PASS provisional | 204.762 | semantic wording 1회 |
| A3-1 | environment | PASS | PASS provisional | 210.000 | 0회 |
| A3-2 | food | PASS | PASS provisional | 260.000 | timing 1회 |
| A4 | housing | PASS | PASS provisional | 180.000 | semantic wording 1회 |
| A5 | technology | PASS | PASS provisional | 245.455 | 1회로 보고됐으나 기존 review JSON에 breakdown 미기록 |
| B1 | education | PASS + semantic warning | PASS provisional | 221.739 | 기존 review JSON에 미기록 |
| B2 | workplace | PASS + semantic warning | PASS provisional | 260.000 | mechanical 2회 + semantic 1회 |

B1은 project-based assessment 논거에서 작품 전시의 mural·gallery 미학으로 자연스럽게 미끄러진
뒤 assessment policy로 돌아온다. B2는 같은 CON speaker가 four-day schedule을 retention의
필요조건이라고 한 뒤 필요조건이 아니라고 직접 부정한다. 두 경우 모두 자동 구조검사와 별도로
transcript-only 의미를 읽고 PASS했다.

## Batch 다양성

`validate_batch_diversity.py` 최종 결과는 PASS다.

- Sample: 9
- Taxonomy coverage: 9/9
- Unique exact motion: 9/9
- Unique domain: 9/9
- Unique motion family: 9/9
- Unique MOD style: 9/9
- Unique participant set: 9/9
- 한 domain의 최대 재사용: 1
- MOD action 간 최대 token Jaccard: 0.1818

이 수치는 card를 다양하게 복사했다는 사실만 보지 않는다. Exact motion, participant-card 일치,
taxonomy role pattern, trigger text와 MOD action 중복도 함께 검사한다. Domain/motion family와 MOD style의
실제 의미 반영은 각 semantic review에서 별도로 확인했다.

Full-debate route도 기존 short prototype에 A5 variation card를 붙인 smoke test에서 bundled
voice-WPM validator를 자동 선택해 PASS했다. 예상 길이는 215.050초였다. 다만 이번 9종 독립
forward test는 모두 event-window이며, A1~B2 각각을 넣은 full-debate 9종 생성시험은 아니다.

## Forward test에서 발견해 고친 문제

1. 기존 event-window validator는 overlap 관계를 검사했지만, 짧은 구간에 너무 많은 단어를 넣는
   문제를 잡지 못했다. 260 WPM ceiling을 추가했다.
2. 새 ceiling에서 기존 positive fixture 9개 중 8개의 압축 timing 문제가 드러났다. Taxonomy와 text는
   유지하고 timestamp만 수정해 9개 모두 다시 PASS시켰다.
3. 260 WPM 초과 negative mutation을 추가했다. 현재 회귀검사는 positive 9개와 negative 11개다.
4. Fresh agent마다 `semantic_review.json` 상위 field가 달랐다. 이후 생성부터 automatic/semantic status,
   validator/semantic repair와 human validation 여부를 동일 shape로 기록하도록 skill 계약을 추가했다.
5. Variation planner에서 A4 trigger subtype과 timing profile이 서로 다른 값을 받을 수 있던 문제를
   발견해 항상 같은 remaining-time 값으로 묶었다.

## 변이 생성 원칙

반복 데이터를 줄이는 우선순위는 다음과 같다.

1. 이전과 다른 trigger subtype과 role pattern을 먼저 배정한다.
2. Domain과 motion family를 quota 방식으로 분산한다.
3. MOD 기능은 고정하되 surface style을 바꾼다.
4. 허용 범위 안에서 gap, overlap과 개입 시점을 바꾼다.
5. 이름만 바꾼 샘플은 독립 변이로 세지 않는다.
6. B1/B2는 표면 다양성보다 semantic validity를 우선한다.

Seed는 재현을 위한 것이며 품질 보증이 아니다. 새 batch는 새 seed와 이전 generation ledger를 사용해
exact motion, motion family와 MOD 문구 재사용을 점검해야 한다.

## 재현 명령

```bash
python3 skills/generate-debate-taxonomy/scripts/test_variation.py
python3 skills/generate-debate-taxonomy/scripts/validate_examples.py
python3 skills/generate-debate-taxonomy/scripts/validate_batch_diversity.py \
  --expected-csv A1,A2-1,A2-2,A3-1,A3-2,A4,A5,B1,B2 \
  evaluation/samples/*/sample.json
```

## 한계

- 의미검사는 fresh generation agent와 root Codex의 transcript-only 검토이며 human gold가 아니다.
- Timestamp는 260 WPM ceiling을 만족하는 synthetic event timeline이다. 실제 TTS 길이와 prosody는
  합성 후 다시 측정해야 한다.
- Taxonomy별 한 sample이므로 domain generalization이나 실패율을 추정할 수 없다.
- 같은 taxonomy의 반복 생성 다양성은 planner regression으로만 확인했다. 실제 대규모 batch에서는
  similarity distribution과 taxonomy별 subtype quota를 다시 측정해야 한다.
- Full-debate diversity routing은 smoke test했지만, full-debate에서 각 taxonomy의 오디오 사건을 모두
  개별 검증한 것은 아니다.
