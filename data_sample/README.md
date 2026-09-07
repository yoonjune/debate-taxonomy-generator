# data_sample — 토론 진행자 벤치마크 21편

Full-duplex 음성 모델을 **토론 진행자 자리에 앉히고**, 언제 말하고 무엇을 말하는지를 잰다.

토론자 오디오는 처음부터 끝까지 그대로 튼다. 모델 채널은 열어 둔다 — 침묵도 정답도 넣지 않는다.
정답 진행자가 말했어야 할 자리(trigger)마다 **언제**(창) **무엇을**(binary) 말했는지 채점하고,
그 밖의 발화는 전부 기록해 따로 판정한다.

```
토론 21편 · 발화 663개 · trigger 199개 · 크로스파이어 2:30 고정
```

## 1. 진행자의 아홉 가지 행동

| | 코드 | 이름 | 언제 | 필수/선택 |
|---|---|---|---|---|
| A 진행 | `A4` | 10초 고지 | 30초 발화가 20초를 지남 / 크로스파이어가 2:20에 이름 | 필수 |
| | `A2-2` | 제시간 종료 후 넘김 | PRO가 30초 안에 끝냄 | 필수 |
| | `A3-1` | 크로스파이어 개시 | 두 오프닝이 끝남 | 필수 |
| | `A3-2` | 클로징 개시 | 크로스파이어 2:30 | 필수 |
| | `A1` | 초과 중단 (다음 화자 없음) | 라운드 마지막 화자 CON이 30초를 넘김 | 선택 |
| | `A2-1` | 초과 중단 후 넘김 | PRO가 30초를 넘김 | 선택 |
| | `A5` | 끼어들기 차단 | 오프닝/클로징에 상대가 끼어듦 | 선택 |
| B 내용 | `B1` | 논제 복귀 | 한 턴 내내 논제를 벗어남 | 선택 |
| | `B2` | 자기모순 지적 | 같은 화자의 절대 규칙 vs 그걸 깨는 사례 | 선택 |

필수는 매 편, 선택은 편당 2~3개를 균등하게 넣었다 (A1 11 · A2-1 11 · A5 11 · B1 14 · B2 10). `A1`과 `A2-1`은 같은 30초 컷이고,
라운드의 첫 화자(PRO)면 넘겨야 하므로 `A2-1`, 마지막 화자(CON)면 부를 사람이 없어 `A1`이다.

## 2. 파일

```
data_sample/
├── README.md              이 문서
├── system_prompt.md       모델에게 주는 지시 (자리표시자 3개)
├── eval_rubric.json       창·binary 기준·창 밖 판정 규격 (기계용)
├── score_freerun.py       채점기: 모델 발화 로그 → timing 분류 + judge 패킷
├── run_judge.py           judge 실행 (OpenAI 호환 모델, --yes 필수)
├── report.py              코드별 표·혼동행렬 집계
├── baselines.py           기준선 3종 발화 로그 생성 (침묵 / 마감마다 / 토론자가 멈출 때마다)
├── debates.jsonl          토론 · 한 줄 = 한 편
├── probes.jsonl           trigger · 한 줄 = 채점 지점 1개
├── audio/mix/L000.wav     완성본 (참고용 · 모델 입력엔 쓰지 않음)
├── audio/mix/L000.json    타임라인 (턴별 시작·끝 초)
├── audio/turns/L000_003.wav  발화 하나짜리 — 토론자 채널은 이걸로 만든다
├── voices/                합성 레퍼런스
└── transcripts/L000.txt   사람이 읽는 대본
```

**오디오는 아직 없다.** GPU가 비는 대로 합성해 `audio/mix/*.wav`, `audio/turns/*.wav`, `voices/`를 채운다. 지금 `audio/mix/<id>.json`의 시각은 단어수 기반 계획값(170 wpm)이고, 합성 뒤 실제 시각으로 다시 쓴다 (탐침 창도 그때 확정).

## 3. 돌리는 법

1. `system_prompt.md`의 `{{MOTION}}` `{{PRO_NAME}}` `{{CON_NAME}}`을 그 편 값으로 치환한다 (`debates.jsonl`의 `motion`, `speakers`). 크로스파이어 길이(2분 30초)는 프롬프트에 고정되어 있다.
2. 토론자 채널 = `audio/turns/`의 **PRO·CON 턴만** `audio/mix/<id>.json`의 `start_sec`에 놓는다 (24 kHz 모노). 진행자(MOD) 턴은 넣지 않는다 — 그 자리는 모델이 채운다.
3. 실시간처럼 흘려보낸다. 모델 출력 채널은 처음부터 끝까지 열어 둔다. 침묵을 강제하지 않고, 정답을 주입하지 않는다.
4. 모델이 말할 때마다 기록한다: `{"debate_id", "start_sec", "end_sec", "text"}` — `start_sec`은 모델 채널의 발화 시작(에너지 VAD: 20 ms 프레임, 최소 발화 200 ms, 최소 침묵 600 ms), `text`는 모델 텍스트 스트림(없으면 ASR). 한 줄에 발화 하나, `utterances.jsonl`.

```bash
python3 score_freerun.py --probes probes.jsonl --debates debates.jsonl --utts utterances.jsonl --out scores/
```

## 4. 채점

**timing** — trigger마다 `[deadline−5, latest+3]` 안의 첫 발화(백채널 제외)를 본다.

| 코드 | 마감 | 창 |
|---|---|---|
| A4 (발화) | 화자 말 시작 + 20s | [18, 22] |
| A4 (크로스파이어) | 크로스파이어 시작 + 140s | [138, 142] |
| A3-2 | 크로스파이어 시작 + 150s | [148, 152] |
| A1 · A2-1 | 화자 말 시작 + 30s | [30, 32] (30초는 보장) |
| A2-2 · A3-1 | 토론자 말 끝 | [끝, 끝+2] |
| A5 | 끼어든 시각 | [0, +2] |
| B1 · B2 | 그 턴 끝 | [끝, 끝+2] |

창 안 `ON_TIME` · 마감 −5초부터 창 앞 `PREMATURE` · 창 뒤 3초 안 `LATE` · 없음 `MISSED`.
크로스파이어 시계(A4 크로스파이어·A3-2)는 **모델 자신의 개시 발화(A3-1)가 끝난 순간**부터 센다. 모델이 개시를 안 했으면 정답 개시 발화 끝(`xf_open_sec`)을 쓴다.
백채널(mm-hm, yeah 같은 필러만, 또는 0.4초 미만 한 단어)은 붙이지 않는다. `"Time."` 같은 한 단어 대사는 정식 발화다. 창이 겹치면(A1 → A3-1) 한 발화가 둘 다에 붙는다.

**content** — 발화 텍스트를 LLM judge가 본다. 코드별 binary, 조건이 둘이면 둘 다.

| 코드 | pass 조건 |
|---|---|
| A4 | "ten seconds"를 말한다 |
| A2-2 | 다음 화자에게 넘긴다 (이름 / 상대편 / 다음 사람) |
| A3-1 | 라운드 전환 **그리고** 길이(2분 30초) |
| A3-2 | 시간 끝 **그리고** 클로징 전환 |
| A1 · A2-1 | 시간 때문에 멈춘다고 한다 |
| A5 | 끼어든 사람에게 멈추라/기다리라고 한다 |
| B1 | 논제로 되돌린다 |
| B2 | 두 주장 모두 언급 **그리고** 되묻는다 |

judge는 `predicted_label`(실제로 무슨 행동을 했나)도 남긴다 → 혼동행렬. `joint = ON_TIME ∧ pass`.

**창 밖 발화** — 어느 trigger에도 안 붙는 발화는 전부 `scores/<id>.json`에 judge 패킷과 함께 남는다. judge는 시스템 프롬프트 + 앞 20초·뒤 5초 대본 + 발화를 보고 `backchannel` / `acceptable` / `awkward` / `violation`(프롬프트의 의무 위반 — 어느 문장인지 인용)으로 판정한다. 함정 구간(잠깐 곁길 뒤 스스로 복귀, 양립하는 두 주장, 크로스파이어 끼어들기)은 `debates.jsonl`의 `traps`에 턴 번호로 남고, 그 구간의 발화는 `trap` 라벨이 붙는다. 시작의 형식 고지와 마지막 마무리는 기대되는 발화라 판정하지 않는다.

**보고** — `report.py`: 코드별 timing 분포 · onset−마감 중앙값/IQR · content pass · joint · 혼동행렬. 편별 창 밖 발화 수와 판정 분포. 기준선 셋(`baselines.py`): 늘 침묵 / 마감마다 말함 / 토론자가 멈출 때마다 말함.

## 5. debates.jsonl · probes.jsonl

`debates.jsonl` 한 줄 = 한 편: `debate_id`, `motion`, `speakers{MOD,PRO,CON}{name,gender,voice_id}`, `selective`(넣은 선택 코드), `crossfire_sec`(150), `xf_open_sec`(정답 개시 발화 끝 = 폴백용 시계 시작), `traps[]`(함정 구간: `kind`, `after_turn`), `timing`(`simulated_170wpm`이면 합성 전), `turns[]`(`i`, `speaker`, `phase`, `code`, `text`, `cut_off`, `src_i`).
`probes.jsonl` 한 줄 = trigger 1개: `probe_id`, `debate_id`, `label`(코드; A4는 `code`에 `A4`/`A4xf`로 구분), `before_turn`(정답 진행자 턴 번호), `t_earliest`, `t_deadline`, `t_latest`, `trigger`(원인 턴·원문·정답 발화).

## 6. 알려진 한계

- 토론자 둘이 한 채널에 섞여 들어간다. A5·B2는 목소리로 사람을 구분해야 한다.
- 토론자 오디오는 정답 진행자를 기준으로 녹음됐으므로, 넘김 자리에 진행자가 말할 만큼의 빈틈이 남아 있다 (모델이 단서로 쓸 수 있음).
- 크로스파이어 A4는 140초짜리 시계다. 모델이 개시 발화를 스스로 안 했다면 시작점을 토론자 소리로만 추정해야 한다.
- 대본은 LLM(gpt-5.6-luna)이 토론자 슬롯만 쓴 것이고, 진행자 대사는 실제 토론(IQ2·OpenToDebate·Doha·Munk)의 발화를 익명화한 시드다. 필터(규칙 + 엄격한 LLM 심사)를 통과한 편만 담았다.
- 이 판은 대본·타임라인·탐침만 있고 오디오는 합성 전이다. 시각은 계획값.

## 7. 출처

진행자 시드: Intelligence Squared US, Open to Debate, Doha Debates, Munk Debates 전사. 목소리: NaturalVoices/MSP-Podcast 레퍼런스로 OmniVoice 합성.
