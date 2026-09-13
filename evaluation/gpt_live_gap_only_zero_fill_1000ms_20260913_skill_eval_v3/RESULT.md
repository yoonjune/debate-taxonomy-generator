# GPT-Live moderator duplex 평가 결과 (5 cases)

## 평가 조건

- 기준: `EVAL_SETTING.md`
- 평가 단위: 제거된 moderator 발화 `mod_turn_id`
- 평가 대상: 5 cases, 총 35개 GT 발화
- Case별 GT: L107 6, L033 6, L079 7, L075 7, L040 9
- 의미 평가는 fresh blinded GPT-Luna review와 별도 disagreement adjudication으로 수행
- `human_gold: false`; exposed development 5-case 결과이므로 correctness나 release gate로 일반화하지 않음

## 전체 결과

| metric | result |
|---|---:|
| ON_TIME | 13/35 |
| LATE | 11/35 |
| PREMATURE | 1/35 |
| MISSED | 10/35 |
| Content correct | 5/35 (0.142857) |
| Joint: ON_TIME and content correct | 2/35 (0.057143) |
| PCM-VAD barge-in | 13/46 (0.282609) |
| Mechanical checks | 5/5 PASS |

## Case별 primary 결과

| case | n | ON_TIME | LATE | PREMATURE | MISSED | content mean | joint mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| L107 | 6 | 2 | 1 | 1 | 2 | 0.166667 | 0.000000 |
| L033 | 6 | 1 | 4 | 0 | 1 | 0.166667 | 0.000000 |
| L079 | 7 | 3 | 2 | 0 | 2 | 0.285714 | 0.142857 |
| L075 | 7 | 3 | 2 | 0 | 2 | 0.142857 | 0.142857 |
| L040 | 9 | 4 | 2 | 0 | 3 | 0.000000 | 0.000000 |

## Code별 primary 결과

| code | n | timing distribution | content mean | joint mean | median onset−deadline (sec) |
|---|---:|---|---:|---:|---:|
| A1 | 1 | LATE 1 | 0.000000 | 0.000000 | 3.086001 |
| A2-1 | 3 | LATE 3 | 0.333333 | 0.000000 | 2.815733 |
| A2-2 | 7 | ON_TIME 5 / LATE 1 / MISSED 1 | 0.142857 | 0.142857 | 1.554244 |
| A3-1 | 5 | ON_TIME 5 | 0.000000 | 0.000000 | 1.469497 |
| A3-2 | 5 | MISSED 1 / LATE 3 / ON_TIME 1 | 0.400000 | 0.000000 | 2.574553 |
| A4 | 8 | MISSED 8 | 0.000000 | 0.000000 | — |
| A5 | 1 | LATE 1 | 0.000000 | 0.000000 | 3.914721 |
| B1 | 3 | PREMATURE 1 / LATE 2 | 0.000000 | 0.000000 | 2.101885 |
| B2 | 2 | ON_TIME 2 | 0.500000 | 0.500000 | 1.503875 |
| A4xf | 0 | 해당 primary row 없음 | 0.000000 | 0.000000 | — |

A4와 A4xf는 서로 다른 clock task이므로 합산하지 않았다. MISSED row는 매칭 발화가 없어 content가
UNKNOWN이지만, aggregate content mean과 joint mean은 frozen 35-row 분모를 사용했다.

## Barge-in 및 non-trigger 결과

- Non-backchannel model utterances: 46
- Operational PCM-VAD barge-in: 13
- Barge-in 분류: on-time correct 0, late required and correct 1, premature but content-correct 0,
  other matched 2, stale required action 0, other contextually acceptable 0, awkward/violating 10
- Non-trigger 12건: acceptable 1, awkward 0, violation 11
- Opening announcement와 closing line은 사전 정의한 extra-speech exclusion에 따라 `NOT_SCORED`

## Anchor 처리

5개 case 모두 A3-1 후보가 round-change criterion을 충족하지 않아 A4xf/A3-2 deadline에는
`xf_open_sec` reference fallback을 적용했다. A3-1 발화가 crossfire를 열었다고 간주해 deadline을
재계산하지 않았다.

## 해석과 한계

- Joint 성공은 L079 B2와 L075 A2-2의 2건이다.
- Mechanical checks는 source/gap/timeline join, exact-zero registered gap, timing reconciliation과
  transport 조건을 포함해 5/5 PASS였다.
- 비교 baseline은 실행되지 않아 수치를 보고하지 않는다.
- Content와 non-trigger 판정은 GPT-Luna 기반 provisional 결과이며 human gold가 아니다.
- PCM-VAD barge-in은 operational diagnostic이며 semantic gold가 아니다.
- 이 GitHub 폴더에는 사용자 요청에 따라 이 결과 문서만 게시하며 WAV, HTML, JSON과 중간 판정 파일은 포함하지 않는다.
