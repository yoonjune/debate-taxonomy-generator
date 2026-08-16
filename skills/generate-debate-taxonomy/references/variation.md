# Controlled variation

## 목적

Taxonomy의 불변조건은 고정하고, 내용과 표면형만 계획적으로 바꾼다. 무작위 단어 치환은 다양성처럼
보여도 trigger의 자연스러움이나 label validity를 해칠 수 있으므로 사용하지 않는다.

## Variation card

생성 전에 다음 여섯 축을 고정하고 `sample.json`의 `variation`에 그대로 기록한다.

| 축 | 바꾸는 것 | 바꾸지 않는 것 |
|---|---|---|
| domain / motion family | 교육, 환경, 노동, 도시정책 등의 논제 영역 | 논제가 양측 토론 가능한지 여부 |
| trigger subtype | 같은 taxonomy가 발생하는 구체적 원인 | taxonomy의 필수 선행조건 |
| role pattern | PRO/CON 중 누가 floor·interrupt·claim을 담당하는지 | MOD/PRO/CON 3역할 계약 |
| moderator style | firm, formal, conversational 등 표면 문구 | MOD action의 기능과 중립성 |
| timing profile | 허용 범위 안의 overlap·gap·개입 시점 | deadline, 8–12초, 0.5초 같은 경계 |
| participant set | 이름과 full-debate voice 조합 | 역할 고유성과 voice provenance |

예시:

```json
{
  "variation_id": "batch7-a4-01",
  "seed": "batch7",
  "domain": "public-health",
  "motion_family": "consumer-policy",
  "trigger_subtype": "ten-second-warning",
  "role_pattern": "CON_floor",
  "moderator_style": "minimal-neutral",
  "timing_profile": "remaining-10s",
  "participant_set": "set-04"
}
```

## Taxonomy별 안전한 trigger subtype

| Taxonomy | 허용 subtype 예시 |
|---|---|
| A1 | unfinished-summary, final-example-overrun, rebuttal-clause-overrun |
| A2-1 | overrun-to-opponent, repeated-point-overrun, unfinished-list-handoff |
| A2-2 | completed-opening, completed-answer, completed-rebuttal |
| A3-1 | PRO-direct-question-first, CON-direct-challenge-first, open-floor-response |
| A3-2 | hard-time-boundary, natural-direct-debate-wrap, moderator-scheduled-close |
| A4 | remaining-8s, remaining-10s, remaining-12s |
| A5 | brief-denial, clarification-interrupt, premise-correction |
| B1 | anecdotal-drift, implementation-detail-drift, aesthetic-side-topic |
| B2 | necessary-vs-sufficient, universal-vs-none, required-policy-vs-rejected-policy |

B1은 무관한 문장을 갑자기 삽입하지 말고 직전 논거의 단어에서 곁가지로 미끄러지게 한다. B2는
`should`와 `need`, 조건 추가와 철회처럼 양립 가능한 차이를 모순으로 쓰지 않는다.

## Batch allocation

1. `plan_variations.py`로 batch 전체 card를 먼저 만든다.
2. 각 생성 worker에는 자기 card 하나만 준다.
3. 같은 batch에서 motion과 variation ID를 재사용하지 않는다.
4. 결과를 모두 만든 뒤 `validate_batch_diversity.py`로 구조와 다양성을 함께 검사한다. Event-window는
   event validator를, full-debate는 bundled voice-WPM validator를 자동 사용한다.
5. 다양성 실패는 taxonomy나 acceptance threshold를 바꾸지 않고 motion·표면형만 한 번 수정한다.

Semantic review에서는 motion이 card의 domain/motion family에 실제로 속하는지, MOD 문체가 배정된
style과 대체로 맞는지도 확인한다. Card를 JSON에 복사하기만 하고 transcript에 반영하지 않은 경우는
variation PASS가 아니다.

```bash
python3 skills/generate-debate-taxonomy/scripts/validate_batch_diversity.py \
  --expected-csv A1,A2-1,A2-2,A3-1,A3-2,A4,A5,B1,B2 sample-*.json
```

## 반복 생성

- 같은 taxonomy를 다시 만들 때 새 seed를 기록한다.
- 이전 batch ledger가 있으면 이미 쓴 exact motion, motion family와 MOD 문구를 피한다.
- 같은 taxonomy의 여러 variant는 role pattern과 trigger subtype을 먼저 바꾸고, 이름만 바꾸는 것은
  독립 variant로 세지 않는다.
- seed는 재현용 식별자이지 품질 보증이 아니다. 생성 후 항상 taxonomy validator와 semantic review를
  다시 수행한다.
