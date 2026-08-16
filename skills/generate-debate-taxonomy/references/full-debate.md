# Full-debate route

Short/long 전체 토론은 이 skill에 포함된 별도 계약과 voice-WPM validator를 사용한다. Event-window용
`contract.json`과 `validate_sample.py`는 개별 taxonomy 사건을 빠르게 검토하기 위한 것이며 전체 토론의
음성 길이를 검증하지 않는다.

## 반드시 읽을 파일

1. `taxonomy.md`: 각 코드의 필수 trigger와 action
2. `generation-rules.md`: 공통 생성·번역·보고 규칙
3. `full-debate-contract.json`: 3-phase 구조와 길이 기준
4. `full-debate-prompt.md`: 전체 토론 JSON schema와 생성 지시
5. `default-voice-profiles.json`: 재현용 기본 timing profile

기존 sample을 복제하지 말고 variation card에 맞는 새 motion, trigger, 참가자와 moderator wording을
사용한다.

## 기본 voice assignment

| 역할 | voice ID | 용도 |
|---|---|---|
| MOD | `MSP-PODCAST_0537_440` | 기본 moderator timing |
| PRO | `MSP-PODCAST_0177_72` | 기본 proposition timing |
| CON | `MSP-PODCAST_0941_297` | 기본 opposition timing |

Bundled voice 파일은 오디오가 아니라 word-length band별 `sec_per_word` metadata다. 원 catalog에서는
각 voice의 합성 test clip 28개가 ASR CER 0 조건을 만족했지만, 이는 실제 음질이나 human validity를
보증하지 않는다. 다른 profile을 사용하려면 같은 `voices -> voice_id -> by_length -> band ->
sec_per_word` shape의 JSON을 만들고 `--voices`로 넘긴다.

## 생성 및 자동 검증

- 각 participant에 `voice_id`를 지정한다.
- 각 turn에는 `gap_after_sec`, `overlap_sec`, `overlap_with`를 기록한다.
- 임의의 `start_sec`/`end_sec`로 전체 길이를 맞추지 않는다.
- Short는 210–225초, Phase 2는 65–80초다.
- Long은 300–330초, Phase 2는 150–180초다.
- 길이는 voice별 word-length band의 `sec_per_word`로 계산한다.

```bash
python3 skills/generate-debate-taxonomy/scripts/validate_full_debate.py transcript.json
```

구조와 WPM timing이 PASS한 뒤 영어 원문을 바꾸지 않고 turn ID별 한국어 참고 번역을 만든다. 아래
renderer는 transcript turn과 번역 key가 정확히 일치하는지, 번역이 비어 있지 않은지, automatic
validation이 PASS인지 확인한다.

```bash
python3 skills/generate-debate-taxonomy/scripts/render_full_debate.py \
  transcript.json validation.json translations_ko.json > sample.md
```

## 검증 범위

Full-debate validator가 자동 확인하는 핵심은 다음과 같다.

- MOD/PRO/CON 세 역할, phase 순서, A3-1/A3-2 위치, PRO-first closing
- target/event link와 taxonomy 3–5개
- A5의 interrupter/floor 관계, overlap과 최대 12단어
- B2 trigger의 same-speaker 구조
- voice-WPM 예상 길이, Phase 2 길이, PRO/CON 균형, MOD word share

A1, A2-1, A2-2와 A4의 세밀한 deadline/overlap topology, B1의 실제 논제 이탈, B2의 논리적
비양립성은 full-debate validator만으로 확정하지 않는다. `taxonomy.md`를 적용한 transcript-only semantic
review가 필요하다. 이들 코드의 더 엄격한 기계 검증이 필요하면 event-window schema와
`validate_sample.py`를 사용한다.

## 보고 구분

- `automatic validation`: bundled validator가 검사한 구조·timing 결과
- `semantic review`: taxonomy trigger, 논거 균형, moderator 중립성에 대한 transcript-only 검토
- `human validation`: 사람이 실제 검토했을 때만 사용

WPM 계산치는 합성 전 예상 길이다. 실제 합성 길이나 human validity로 표현하지 않는다.
