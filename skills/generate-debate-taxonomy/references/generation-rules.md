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

## 마지막 통과 — 대본 전체를 한 번 읽는다

슬롯을 다 채운 뒤, 대본을 처음부터 끝까지 **하나의 대화로** 한 번 읽는다. turn을 하나씩
보는 것이 아니라 토론을 본다. 이 통과에서 다음을 고친다.

- 각 turn이 배정된 진영을 첫 turn부터 마지막까지 유지하는가. 모순을 지적당한 뒤에도 유지되는가.
- 토론자 turn이 진행자 대사를 미리 말하거나 따라 하지 않는가.
- 자기 이름을 3인칭으로 부르거나, 아무도 하지 않은 말에 답하거나, 같은 말을 두 번 하지 않는가.
- 진행자 발화가 방금 실제로 일어난 일에 걸리는가. 그 뒤 turn이 개입의 결과를 보이는가.
- 라운드와 어휘가 맞는가. 오프닝에서 `closing`, 클로징에서 `opening`을 말하지 않는가.

이 통과는 실측에서 자기 이름 3인칭을 13 → 3 turn으로, 하이픈 오종결을 12 → 3 turn으로 줄였다.
비용은 편당 입력 180 토큰 정도다.

## 연출 금지

진행자 행동을 넣으려고 만든 상황처럼 보이면 안 된다. 토론자는 문제를 예고하지 않고, 일부러
시간을 넘기지 않고, 뜬금없이 화제를 바꾸지 않고, 방금 한 말의 정반대를 말하지 않는다. 상황을
먼저 쓰고 진행자가 거기에 반응하게 한다. 배정표를 보지 않은 사람이 읽었을 때 어떤 코드를
노렸는지 알 수 있으면 실패다.

동시에 **개입 자체를 아껴야 한다.** 코드가 붙은 진행자 turn은 한 편에 여덟 개를 넘지 않는다.
4분짜리 토론에 열한 번의 개입이 들어가면 그것만으로 체크리스트로 읽힌다.

## 진행자가 알 수 있는 것

진행자는 이 대본에 나온 것만 안다. 과거 입장, 지난 방송, 경력, 대본이 말하지 않은 이력은
없는 정보다. `지난 몇 년간 당신은…` 이라고 말하는 순간 근거를 지어낸 것이고, 그 지적은
transcript만으로는 채점할 수 없게 된다.

## 낭독을 전제로 쓴다

최종 출력은 음성 합성으로 읽힌다. 짧은 문장, 무엇에 대한 말인지 먼저 밝히는 어순, 평범한
축약형과 연결어를 쓴다. 문장부호는 ASCII만 쓴다. 지목은 `you`로 한다 — 태그 없는 `he`/`she`는
듣는 사람이 누구인지 알 수 없다.
