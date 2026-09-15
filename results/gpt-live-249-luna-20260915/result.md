# GPT-Live 251-case 재시도 및 Luna 평가 결과

## 결론

- 3건을 현재 고정 조건으로 다시 실행했다.
- `L006`은 `COMPLETE`가 되었고 평가에 포함했다.
- `L185`, `L226`은 재시도에서도 GPT-Live provider의 `content_filter`가 동일하게 발생했다. 완성된 inference artifact가 없으므로 평가에서 제외했다.
- 최종 평가 범위는 **249/251 cases**, case별 실제 GT를 합한 **2,364 probes**다.
- 결과 상태는 `PROVISIONAL_COMPLETE`이며 semantic review 누락은 0개다. `human_gold=false`이므로 correctness gold로 해석하지 않는다.

## GitHub 원본 일치성

- 비교 원격: `https://github.com/yoonjune/debate-taxonomy-generator.git`
- 비교 ref: `origin/renewal-30`
- 원격/로컬 commit: `a8ad4ba22c83fb5e5802a4b4e33e9a53f8c6e1a3`
- case universe: `L000`–`L250`, 251개
- case별 mix artifact: MP3 251개 + JSON 251개
- source snapshot 전체 검사: 516 files, SHA-256 mismatch 0, missing 0

따라서 **251개 원본 case와 source snapshot은 GitHub `renewal-30` 데이터와 정확히 일치한다.** 단, 실제 전송용 `input.wav`/`user.wav`는 원본 MP3의 byte copy가 아니다. EVAL_SETTING에 따라 moderator 구간을 exact-zero로 바꾼 파생 transport input이다. `L006`에는 마지막 GT source clock을 보존하기 위해 participant 음성을 바꾸지 않고 끝에 exact-zero 0.2초만 추가했다.

## 최종 지표

| 지표 | 결과 |
|---|---:|
| 평가 cases | 249 / 251 |
| GT probes | 2,364 |
| ON_TIME | 709 (29.99%) |
| LATE | 445 (18.82%) |
| PREMATURE | 189 (7.99%) |
| MISSED | 1,021 (43.19%) |
| Content mean | 0.332699 |
| Joint mean | 0.196489 |
| Non-backchannel utterances | 2,518 |
| Barge-ins | 1,127 (44.76%) |
| Mechanical contract | 249 / 249 PASS |

### Barge-in 의미 분류

| 분류 | 건수 |
|---|---:|
| ON_TIME required and correct | 41 |
| LATE required and correct | 42 |
| PREMATURE but content correct | 108 |
| Other matched barge-in | 201 |
| Stale required action | 12 |
| Other contextually acceptable | 80 |
| Other awkward or violating | 643 |

## Luna review provenance

- 기존 blinded packet과 canonical JSON이 동일한 2,428개 판정만 재사용했다.
- 새 `L006` 관련 10개 항목은 fresh, blinded `gpt-5.6-luna` session으로 평가했다.
- 최종 semantic review: 2,438 / 2,438, missing 0.

## 제외 사례

| Case | 재시도 결과 | 평가 제외 이유 |
|---|---|---|
| L185 | `ERROR: content_filter` | provider moderation으로 complete output 부재 |
| L226 | `ERROR: content_filter` | provider moderation으로 complete output 부재 |

두 사례를 필터 우회나 입력 변경으로 다시 실행하면 현재 실험과 다른 조건이 되므로, 본 결과에서는 실패를 보존하고 제외했다.

## 재현 artifact

- `../source_data_audit.json`: GitHub source SHA audit
- `../campaign-index.json`: 3-case retry 상태
- `evaluation_exclusions.json`: denominator 및 제외 근거
- `full_stage/`: deterministic 평가 산출물
- `full_delta_l006/review.json`: 새 L006 Luna review
- `full_reviews_merged_249.json`: 동일 packet 재사용 provenance 포함 병합 review
- `final_evaluation.json`: 최종 machine-readable 결과
