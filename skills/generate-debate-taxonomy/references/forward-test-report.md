# Fresh-agent forward test — 2026-08-16

이 검사는 example catalog를 보지 않은 fresh GPT-5.6 Luna session에 실제 사용자형 요청을 주고,
skill 지침만으로 산출물을 생성·검증하게 한 forward test다. 결과는 same-family model 검토이며
human validation이 아니다.

## 결과 요약

| 요청 | 경로 | 최초 결과 | 최종 결과 | Loop에서 확인한 것 |
|---|---|---|---|---|
| `A3-1을 만들어줘` | event-window | PASS | PASS | 양쪽 opening 뒤 A3-1, 이어 직접 응답 |
| `A4를 만들어줘` | event-window | validator 최초 PASS 뒤 교차검사에서 표현 오류 발견 | PASS, local repair 1회 | 같은 PRO turn 중복 overlap을 새 규칙이 FAIL로 잡고 국소 수정 |
| `B2가 들어간 short 토론을 만들어줘` | full-debate | 임의 timestamp로 220초를 만든 잘못된 경로 | PASS, full regeneration 1회 + semantic local repair 1회 | voice-WPM 경로 강제, 엄밀한 B2 양립 불가능성 검토 |

## 최종 자동 지표

- A3-1 event-window: 자동 오류 0, validator repair 0회
- A4 event-window: 자동 오류 0, 동일 화자 중복 overlap 제거, local repair 1회
- B2 short full-debate: voice-WPM 예상 219.264초
  - Phase 1: 74.975초
  - Phase 2: 73.011초
  - Phase 3: 71.278초
  - PRO/CON 발화시간 비율: 1.0546
  - MOD 단어 비율: 0.1417

B2 최종 trigger는 같은 PRO가 먼저 `structured practice`를 필요조건으로 말하고, 나중에
`passive entertainment alone`으로 충분하다고 말하는 두 주장이다. MOD는 이 두 가시적 주장을
대조한다. 이는 transcript-only semantic review에서 PASS했지만 사람이 확인한 gold는 아니다.

## 발견으로 바꾼 규칙

1. Event-window validator에 동일 화자 turn overlap 금지를 추가했다.
2. Full-debate를 event-window timestamp validator로 통과시키지 못하게 했다.
3. Full-debate는 bundled perfect-CER0 timing profile의 length-band WPM validator로만 길이를 판정한다.
4. Full-debate renderer가 transcript와 한국어 번역 key의 완전 일치를 검사한다.
5. B2는 구조 PASS 뒤에도 modal, scope, qualification 차이를 따로 읽고 검토한다.

## 회귀검사

`scripts/validate_examples.py`의 9개 positive fixture와 11개 negative mutation이 모두 기대대로
통과/실패했다. B1/B2의 의미 타당성은 자동 결과와 분리한다.

## 전체 9종 재검사

같은 날 example을 보지 않은 fresh GPT-5.6 Luna session 9개로 A1, A2-1, A2-2, A3-1, A3-2,
A4, A5, B1, B2를 각각 생성했다. Root가 모든 JSON을 독립 재검사했고 최종적으로 9종 모두 automatic
PASS와 transcript-only semantic PASS를 얻었다. Bounded repair가 필요했던 사례도 포함하므로 이는
first-pass 9/9가 아니다.

Controlled variation batch 결과:

- unique motion/domain/motion family/MOD style/participant set: 각각 9/9
- maximum MOD-action token Jaccard: 0.1818
- batch validator: PASS

검사 과정에서 event-window 260 WPM ceiling, A4 variation timing 정합성과 공통 semantic-review artifact
shape를 추가했다. 전체 raw 산출물과 상세 결과는
`evaluation/RESULTS_KO.md`에 보존한다. 현재 회귀검사는 positive 9개,
negative 11개다.
