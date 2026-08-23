# Generation and output rules

## Modes

### event-window

Taxonomy 하나를 빠르게 검토하는 기본 mode다. Trigger 이전, MOD action, 결과를 포함하는 4–8개
turn을 생성한다. 전체 토론 길이나 voice WPM을 요구하지 않는다. 모든 turn에 실제 audio timeline을
나타내는 `start_sec`와 `end_sec`를 기록한다.

### full-debate

Short 또는 long 3-phase 토론을 생성한다.

- Short: 210–225초
- Long: 300–330초
- Phase 1: MOD 소개, PRO opening, CON opening
- Phase 2: A3-1, 직접 토론, 선택 taxonomy event
- Phase 3: A3-2, PRO closing, CON closing
- A3-1/A3-2 필수, 전체 taxonomy 3–5개

Full-debate는 이 문서의 event-window timestamp schema를 쓰지 않는다. 반드시
`references/full-debate.md`에 연결된 bundled contract와 voice length-band WPM validator를 사용한다.
LLM이 임의로 `start_sec`/`end_sec`를 배정해 목표 길이를 맞춘 것으로 처리하지 않는다.

## Assignment

생성 전에 다음을 고정한다.

- `mode`
- `motion`
- `participants`: MOD/PRO/CON 정확히 세 역할
- `target_taxonomies`
- `duration_profile` 또는 event window 길이
- 사용한 seed의 dataset/debate/turn locator

Full debate motion은 `usable=true`만 사용한다. 이 프로젝트에서는 IQ2 quarantine conversation
`0`, `3416`, `5488`, `5977`, `9437`, `11767`, `14199`, `20418`, `23312`를 제외한다. Exact duplicate와
여러 taxonomy에 동시에 배정된 ambiguous seed도 제외한다.

## JSON shape

```json
{
  "schema_version": "0.1",
  "mode": "event-window",
  "sample_id": "a4_example_001",
  "motion": "Video games will make us smarter.",
  "participants": {
    "MOD": {"name": "Alice"},
    "PRO": {"name": "Daniel"},
    "CON": {"name": "Sarah"}
  },
  "target_taxonomies": ["A4"],
  "turns": [
    {
      "turn_id": "t001",
      "phase": 2,
      "speaker": "PRO",
      "text": "...",
      "start_sec": 0.0,
      "end_sec": 14.0,
      "taxonomy": []
    }
  ],
  "events": [
    {
      "taxonomy": "A4",
      "moderator_turn_id": "t002",
      "trigger_turn_ids": ["t001"],
      "floor_holder": "PRO",
      "remaining_sec": 10.0
    }
  ],
  "translations_ko": {"t001": "..."}
}
```

Taxonomy-specific event fields are defined in `references/contract.json` and checked by the validator.

## Timeline

- Sort turns by `start_sec`; concurrent turns may overlap.
- Require `end_sec > start_sec`.
- 모든 turn의 평균 발화속도는 260 WPM 이하여야 한다. 이는 voice가 지정되지 않은 event-window의
  과도하게 압축된 timestamp를 막는 보수적 ceiling이며 실제 합성 길이 예측은 아니다.
- 같은 화자의 두 turn은 겹치지 않는다. 이어 말하는 구간을 별도 turn으로 나눌 때도 앞 turn을
  overlap 시작점에서 닫거나, 하나의 연속 turn으로 유지한다.
- Use overlap only when required by A1, A2-1, A4, or A5.
- Do not encode overlap merely by prose; timestamps must intersect.
- Keep MOD utterances short enough to fit their time interval.

## Text and translation

- Actual transcript and TTS target are English.
- Provide one Korean reference translation for every turn ID.
- Preserve names and claim meaning in translation.
- Do not use the Korean translation for English timing.
- Avoid unresolved square-bracket tags, audience speakers, precise invented statistics, named studies, and
  extra participants.
- 화자는 MOD/PRO/CON 셋뿐이다. `everybody`, `everyone at once`, `too many people`처럼 토론자가
  셋 이상임을 전제하는 표현을 쓰지 않는다.
- 합성 입력이므로 TTS 친화 문자만 쓴다. 유니코드 따옴표(`’` `“` `”`)와 엠대시(`—`)를
  ASCII로 정규화한다. 중단 표기는 하이픈 하나(`-`)로 통일한다.
- 진행자 발화 한 turn은 한 가지 일만 한다. 시간 고지를 하면서 다음 화자를 부르는 문장은
  어느 코드에도 속하지 않으므로 쓰지 않는다.

## Rendering

Render English first and place Korean directly below it. Show taxonomy badges, timestamps, overlaps, event
trigger IDs, automatic validation status, and semantic-review warnings.

## Review artifact

각 생성은 다음 공통 shape의 `semantic_review.json`을 남긴다. `checks`의 세부 key는 taxonomy에 맞게
정하되 상위 key는 바꾸지 않는다.

```json
{
  "sample_id": "...",
  "automatic_status": "PASS",
  "semantic_status": "PASS_PROVISIONAL",
  "human_validated": false,
  "validator_repairs": 0,
  "semantic_repairs": 0,
  "full_regenerations": 0,
  "checks": {},
  "limitations": []
}
```

`PASS_PROVISIONAL`은 transcript-only 검토 통과다. 사람이 실제로 검토하지 않았다면
`human_validated`를 `true`로 쓰지 않는다. 각 repair 수에는 실패한 최초 시도 이후 실제로 적용한
수정만 센다.
