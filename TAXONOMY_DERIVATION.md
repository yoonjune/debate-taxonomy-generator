# 진행자 행동 분류 체계는 어떻게 9개가 되었나

작성 2026-09-11 · `_meta/TAXONOMY_DERIVATION.md`
대상 독자: ICASSP 논문 Section "Taxonomy"를 쓰는 사람.

이 문서는 **최종 9코드가 어디서 나왔는지**의 전체 기록이다.
2026년 6월~7월에 돌린 다섯 개의 독립 분석, 각 분석의 산출 수치,
그리고 그 결과를 9개로 좁힌 선택 규칙을 순서대로 적는다.

한 줄 요약: **다섯 분석이 모두 "진행자는 압도적으로 흐름·발언권 관리자"라고 말했고
(최대 클러스터 49.6%), 우리는 그 클러스터 안쪽만 남기고 나머지를 규칙으로 잘라냈다.**

---

## 0. 왜 분류 체계가 필요했나

벤치마크의 단위는 "진행자가 **말해야 하는 자리**"다.
그 자리를 정의하려면 진행자가 실제로 하는 행동의 전체 목록이 먼저 있어야 하고,
그중 **규칙으로 옳고 그름을 판정할 수 있는 것**만 골라야 한다.

기존 연구의 분류 체계를 그대로 쓰지 않은 이유는 두 가지다.

1. 대부분 텍스트 토론 분석용이라 **타이밍(언제 말하는가)** 이 빠져 있다.
   full-duplex 모델 평가에는 "무엇을 말하나" 만큼 "언제 끼어드나"가 핵심이다.
2. 우리 형식은 **3인(MOD/PRO/CON)** 이다. 실제 코퍼스의 진행자 행동 중
   상당수는 청중·패널·투표가 있어야 성립한다. 이식이 불가능하다.

그래서 상향식(데이터에서 올라오는 것)과 하향식(우리 형식에서 성립 가능한 것)을
양쪽에서 맞춰 9개로 수렴시켰다.

---

## 1. 분석의 공통 입력 — 366편 / 31,264 윈도우

네 개의 진행자 있는 정책토론 코퍼스를 썼다.

| 코퍼스 | 토론 편수 | 진행자 윈도우 |
|---|---:|---:|
| IQ2 / Intelligence Squared US | 107 | 10,192 |
| Open to Debate | 180 | 12,748 |
| Doha Debates | 58 | 8,009 |
| Munk Debates | 11 | 315 |
| **합계** | **366** | **31,264** |

- **윈도우 단위** = 진행자 발화 1개 + 앞 4턴 + 뒤 4턴 (맥락용).
  스크립트 `_meta/openclio/extract_windows_all.py`.
  맥락 턴은 각 80단어로 자르고(앞 턴은 뒤쪽, 뒤 턴은 앞쪽을 남김),
  진행자 발화만 600단어까지 온전히 보존한다. 판정 대상이 진행자 발화이기 때문이다.
- **회계 검증**: 코퍼스의 진행자 턴 수 = 유지 + 탈락 임을 소스별로 assert한다.
  탈락은 빈 텍스트와 Munk의 비토론 인터뷰 2편뿐이다.
- 인터뷰·특별행사를 제거해 393 → 366편이 되었다.
- 출력 `_meta/openclio/input/all.jsonl` (128 MB). 이 파일이 **다섯 분석 중 3, 5번과
  최종 라벨링의 공통 입력**이다.

오디오를 쓰지 않은 이유는 따로 있다. IQ2 팟캐스트 피드는 편집본이라
녹취 단어의 약 45%만 담고 진행자 발화는 0% 남는다. 94개 페어 중 15개만 완전 정합.
그래서 실제 오디오는 테스트 신호로 못 쓰고, 우리가 합성하기로 했다.

---

## 2. 분석 ① — IQ2 수작업 21-move 분류 (2026-06-19)

**무엇을**: IQ2 108편 10,246개 진행자 턴을 상향식으로 훑어 21개 무브 목록을 만들고,
20% 층화표본 2,050턴에 손으로 라벨을 붙였다.
산출물 `datasets/A1_IQ2_IntelligenceSquared/MODERATOR_TAXONOMY.md`.

**어떻게**: 네 개의 에이전트가 **독립적으로** 무브 목록을 제안했다.
네 곳에서 공통으로 나온 무브(bare-name 핸드오프, probe, interrupt, 라운드 전환,
결과 발표 등)를 견고한 것으로 보고, 갈리는 것은 데이터로 중재했다.
이어서 21개 정본 목록(M01–M21) + OTHER로 통합하고 표본에 라벨링했다.
독립 재라벨링(160턴)으로 순위 재현성을 확인했다.

**결과 (2,050턴 표본 비율)**

| 순위 | 무브 | 비율 |
|---:|---|---:|
| 1 | M04 이름만 부르는 발언권 넘김 | 16.5% |
| 2 | M08 내용 질문 | 12.0% |
| 3 | M15 청중 Q&A 진행 | 8.9% |
| 4 | M06 맞장구 | 6.8% |
| 5 | M03 소개 + 워밍업 | 6.6% |
| 6 | M12 끼어들기·플로어 통제 | 6.1% |
| 7 | M07 정리하고 넘어가기 | 6.0% |
| 8 | M09 한쪽 주장을 상대에 넘겨 충돌 유발 | 4.9% |
| 9 | M16 청중 질문 다듬기 | 4.9% |
| 10 | M18 클로징 예고 | 4.0% |
| — | M14 시간 경고 | 3.7% |
| — | M13 논제로 되돌리기 | 1.0% |
| — | OTHER 단편 | 4.4% |

**우리가 가져온 것**

- 진행자 발화의 **중앙값이 10단어**, 4단어 이하가 30%. 진행자는 말수가 적다.
  → 우리 시스템 프롬프트의 "한두 문장으로" 규칙의 근거.
- 가장 흔한 단일 행동이 **이름만 부르는 넘김**이다. → A2 계열의 근거.
- 6개 역할 묶음(R1 형식/절차, R2 발언권, R3 내용질문, R4 논제규율,
  R5 청중, R6 판정·방송) 중 **R2와 R4만** 우리 형식에서 살아남는다.

**한계로 기록된 것**: 표본 기반 비율이고, John Donvan 한 사람이 대부분을 진행해서
그의 스타일에 편향돼 있다. M05/M21은 단독으로 잘 서지 않고, M08과 M09의 경계가 모호하다.

---

## 3. 분석 ② — 의회·대법원 7+1 action space (2026-06-19)

**무엇을**: 토론이 아닌 **다른 종류의 진행자** 두 코퍼스를 전수 분류했다.
영국 하원 PMQs 의장 691턴, 미 연방대법원 재판장 1,187턴, 합계 1,878턴.
산출물 `/home/dongwook_lee/ICLR2027/Moderator_Taxonomy.md`.

**어떻게**: 턴마다 7+1개 코드 중 정확히 하나를 붙였다(혼합 턴은 지배적 기능으로 강제).
직전·직후 발화자를 맥락으로 썼다. 95턴을 별도로 검수해 **일치율 92.6%**.

**결과**

| 코드 | 의미 | PMQs | SCOTUS | 합계 |
|---|---|---:|---:|---:|
| A FLOOR_ALLOCATION | 발언권 배분 | 271 (39.2%) | 557 (46.9%) | 828 |
| B ORDER_DISCIPLINE | 질서·발언권 보호 | 241 (34.9%) | 6 (0.5%) | 247 |
| C TIME_PACE | 시간·페이스 | 31 (4.5%) | 53 (4.5%) | 84 |
| D CONTENT_REFEREE | 논점 복귀·답변 압박 | 40 (5.8%) | 39 (3.3%) | 79 |
| E PROCEDURE_ADMIN | 절차·행정 | 81 (11.7%) | 0 | 81 |
| F CEREMONY_SOCIAL | 의례 | 11 (1.6%) | 7 (0.6%) | 18 |
| **G SUBSTANTIVE_PARTICIPANT** | **본안에 직접 참여** | 1 (0.1%) | 491 (41.4%) | **492** |
| OTHER | 단편 | 15 | 34 | 49 |

**이 분석이 준 결정적 기여: 네거티브 클래스**

PMQs 의장은 positive(A–F)가 **97.7%**, 순수 심판이다.
대법원 재판장은 positive가 **55.8%** 뿐이고 **41.4%가 G**다 — 진행이 아니라
사건의 법적 쟁점을 직접 논쟁한다. 두 개의 모자를 같이 쓴다.

우리가 만들려는 건 **PMQs형 진행자**다. 그래서 G를 **실패로 정의**했다.
편들기·승자 선언·본안 참여는 점수를 깎는 행동이다.
이 판단이 나중에 분석 ⑤의 최대 클러스터 중 하나를 통째로 버리는 근거가 된다.

---

## 4. 분석 ③ — IQ2 연역적 5×2 분류 (2026-06-19)

**무엇을**: 사람이 먼저 만든 5대분류 × 2소분류 = 10칸에 IQ2 10,192턴 전수 배정.
모델 `Qwen3.6-35B-A3B` 로컬, 맥락은 앞 2턴 + 진행자 + 뒤 2턴 + phase.
분류 체계 전체를 프롬프트 공유 접두사로 둬 prefix cache를 태웠다.
스크립트 `_meta/llm_label/classify_moderator.py`, 통계 `output/classify_stats.md`.

**결과 — 대분류**

| 코드 | 대분류 | 발화 | 비율 |
|---|---|---:|---:|
| B | 발언권 배분·관리 | 4,725 | **46.4%** |
| D | 후속질문·요약·명확화 | 2,651 | 26.0% |
| A | 토론 구조 조정 | 1,937 | 19.0% |
| C | 시간 관리 | 530 | 5.2% |
| E | 토론 품질·상호작용 | 227 | 2.2% |
| OTHER | | 122 | 1.2% |

**소분류**: B1 발언 순서 안내 41.0% · D2 요약·명확화 19.0% · A1 오프닝 프레이밍 12.5% ·
D1 탐침 질문 7.0% · A2 클로징 6.5% · B2 플로어 보호 5.3% · C1 시간 준수 3.3% ·
C2 초과 처리 1.9% · E2 이탈 복귀 1.5% · E1 무례 완화 0.7%.

**주의 (논문에 쓸 때)**: 이 표의 `A1`, `B1`, `B2`는 **최종 9코드의 A1/B1/B2와 다른 것**이다.
이름만 겹친다. 이 분석은 6월의 중간 산출물이고, 최종 코드는 7월에 재정의됐다.

**우리가 가져온 것**: 발언권 배분이 절반 가까이라는 사실의 첫 번째 정량 확인.
그리고 시간 관리가 5.2%로 **작다**는 것. 실제 진행자는 시간을 자주 말하지 않는다.
우리 형식이 30초 규격을 강제하면서 A4를 필수로 만든 건 이 자연 분포와 다르다.
(한계 절에 명시해야 할 항목이다.)

---

## 5. 분석 ④ — 자유 라벨 → k-means K=25 (2026-06-19)

**무엇을**: 분류 칸을 주지 않고, IQ2 10,192턴 각각에 "진행자가 무엇을 하는가"를
**10단어 이내 자유 동사구**로 쓰게 했다. 중복 제거 후 고유 라벨 6,087개.
이를 `all-mpnet-base-v2`로 임베딩하고 빈도 가중 k-means K=25로 묶은 뒤
각 군집 이름을 LLM이 붙였다.
스크립트 `_meta/llm_label/label_moderator.py` → `kmeans_label.py`.

**상위 군집**

| # | 군집 | 비율 | 대표 라벨 |
|---:|---|---:|---|
| 1 | 다음 발언자 소개·호명 | **21.7%** | introduces the next speaker |
| 2 | 직답 압박 | 9.9% | presses debater for a direct answer |
| 3 | 흐름 관리를 위한 끼어들기 | 6.7% | interrupts the speaker to regain control |
| 4 | 질문 명확화·재구성 | 5.8% | clarifies the debater's question |
| 5 | 시간 준수·전환 | 4.4% | enforces the time limit |
| 9 | 청중 Q&A | 3.8% | opens audience Q&A |
| 14 | 투표·결과 발표 | 2.8% | announces the final debate results |
| 25 | 농담·가벼운 발언 | 1.0% | makes a humorous remark |

**왜 이걸 따로 했나**: 분석 ③은 우리가 만든 칸에 데이터를 밀어 넣은 것이다.
칸 자체가 틀렸을 가능성을 확인하려면 칸 없이 한 번 더 봐야 했다.
결과는 ③과 같은 순위였다 — 호명·넘김이 1위, 직답 압박이 2위.
**칸을 안 줘도 같은 구조가 나온다**는 것이 확인됐다.

---

## 6. 분석 ⑤ — OpenClio 전 코퍼스 상향식 클러스터링 (2026-07-17)

이 분석이 최종 선택의 직접적 근거다.

**무엇을**: 4개 코퍼스 **31,264 윈도우 전체**를 OpenClio로 계층 클러스터링했다.
스크립트 `_meta/openclio/run_openclio.py`, 잡 `run_openclio_all.sbatch`
(pro6000 ×2, vLLM TP=2, `Qwen3.6-35B-A3B`, 임베딩 `all-mpnet-base-v2`).

**facet 설계** — 클러스터링 대상 축은 하나뿐이다.

```
name     ModeratorAction
question What is the single core action the debate moderator performs in their turn —
         their communicative or procedural move in the exchange between the two debaters?
prefill  The moderator is
```

프롬프트는 "MOD가 하는 것만 보라, 선악 판단 말라, **고유명사는 쓰지 말라**,
두 문장 이내"를 지시한다. 고유명사 금지가 중요하다.
넣으면 군집이 주제(중동, 기후)로 갈라져서 **행동** 축이 안 나온다.
녹취 텍스트는 프롬프트 **끝**에 붙여 긴 지시부가 prefix cache에 걸리게 했다.

**설정 메모**: 기본값은 base cluster를 n/10개 만드는데, 200개로 상한을 뒀다
(네이밍 호출 5배 감소). 대신 군집 이름은 **5회 샘플 다수결**로 뽑는다.
1회로 줄이면 약 30%가 `<Could not extract name>`으로 남는다.
실제로 6월의 IQ2 단독 시험 런(`out/iq2/`)이 그 실패를 보여준다 —
상위 군집 2개에 5,753점짜리 **이름 없는 군집**이 생겼다. 그래서 재설정 후 전량 재실행했다.

**결과: 31,224점이 5개 최상위 군집으로** (40점은 중복 제거로 빠짐)

| 최상위 군집 | 점 | 비율 |
|---|---:|---:|
| **Manage debate flow and transitions** | **15,492** | **49.6%** |
| Press debaters for direct answers and correct errors | 8,047 | 25.8% |
| Clarify Statements and Elicit Motivations | 4,283 | 13.7% |
| Facilitate audience Q&A and polls | 2,451 | 7.8% |
| Acknowledge participants and solicit donations with humor | 951 | 3.0% |

**최대 군집 "흐름·전환 관리" 15,492개의 내부**

| 2단계 | 점 | 전체 대비 |
|---|---:|---:|
| Manage speaking turns and debate flow | 7,966 | 25.5% |
| Introduce speakers and audience members | 2,400 | 7.7% |
| Enforce time limits and turn-taking | 2,309 | 7.4% |
| Clarify scope and redirect to original question | 1,476 | 4.7% |
| Conclude debate, declare winner, and transition | 1,341 | 4.3% |

3단계로 더 내려가면 최종 코드와 거의 일대일로 붙는다.

```
Manage speaking turns and debate flow                7,966
├─ Direct the floor to the opposing debater          4,397
│   ├─ Interrupt and yield the floor                 2,502   → A1 / A2-1 / A3-2
│   ├─ Transition to the next speaker                1,303   → A2-2
│   └─ Direct the floor to the opposing debater        592   → A2-2
├─ Assign speaking turns and call on specific debaters 2,227 → A2-2
└─ Manage debate flow and enforce turn-taking        1,342
    ├─ Enforce turn-taking by stopping simultaneous speech 717 → A5
    ├─ Summarize arguments and direct a question       328
    ├─ Transition to Closing Statements                179   → A3-2
    └─ Grant debaters permission to speak or continue  118   → A5

Enforce time limits and turn-taking                  2,309
├─ Enforce turn-taking and time limits               1,085
├─ Enforce time limits and transition to next speaker  866   → A2-1
└─ Enforce time limits and transition speakers         358
    └─ Count down remaining time for speaker            24   → A4

Clarify scope and redirect to original question      1,476
├─ Redirect debaters to the original question        1,296   → B1
└─ Clarify scope and definitions to narrow the debate  180
```

---

## 7. 다섯 분석의 수렴

독립적으로 돌린 다섯 개가 같은 그림을 준다.

| 관찰 | ① 21-move | ② 7+1 | ③ 5×2 | ④ k-means | ⑤ OpenClio |
|---|---|---|---|---|---|
| 발언권 배분이 최대 | M04 16.5% (1위) | A 44.1% (1위) | B 46.4% (1위) | #1 21.7% | 15,492 중 7,966 |
| 시간 관리는 작다 | M14 3.7% | C 4.5% | C 5.2% | #5 4.4% | 2,309 (7.4%) |
| 논제 규율은 더 작다 | M13 1.0% | D 4.2% | E2 1.5% | — | 1,296 (4.2%) |
| 내용 압박이 2위 | M08+M09 16.9% | (D) | D 26.0% | #2 9.9% | 8,047 (25.8%) |
| 청중·투표가 상당 비중 | M15+M16 13.8% | — | — | #9+#14 6.6% | 2,451 (7.8%) |

즉 **"진행자 = 발언권 관리자"** 는 코퍼스·방법·모델을 바꿔도 흔들리지 않았다.
그리고 그 다음으로 큰 덩어리가 **내용 압박**이라는 것도 일관됐다.

---

## 8. 9개로 좁힌 선택 규칙

수렴된 그림에서 최종 코드를 고를 때 쓴 기준은 세 가지다.
**순서대로 적용했고, 각 단계에서 무엇이 왜 탈락했는지가 논문에 필요한 부분이다.**

### 기준 1 — 규칙으로 정오를 판정할 수 있는가

형식이 정답을 결정해야 한다. "30초를 넘겼다"는 관찰 가능하고,
그러면 진행자는 반드시 끊어야 한다. 안 끊으면 오답이다.
반면 "좋은 후속 질문"은 형식이 정답을 주지 못한다.
같은 상황에서 여러 질문이 다 맞다.

**탈락**: 분석 ⑤의 `Clarify Statements and Elicit Motivations` 4,283 (13.7%) 전부.
①의 M08·M09·M11, ③의 D1·D2, ④의 #2·#4가 여기 해당한다.

### 기준 2 — 3인(MOD/PRO/CON) 구조에서 성립하는가

청중이 없으면 청중 질문이 없다. 패널이 없으면 패널 소개가 없다.
사전·사후 투표가 없으면 결과 발표가 없다. 후원 요청은 IQ2 방송 사정이다.

**탈락**:
- `Facilitate audience Q&A and polls` 2,451 (7.8%) — ① M15+M16, ④ #9+#24
- `Conclude debate, declare winner, and transition` 1,341 (4.3%) — ① M19, ④ #14
- `Acknowledge participants and solicit donations with humor` 951 (3.0%) — ① M20, ④ #25
- `Introduce speakers and audience members` 2,400 (7.7%) 중 약력 소개 부분 — ① M03, M21

`Introduce speakers`는 일부만 살렸다. 매 토론 첫 발화의 **형식 고지**는 남기되
(청자와 평가 대상 모델이 규칙을 알아야 이후 개입의 정당성을 판단할 수 있다),
약력·수상경력 소개와 호스트 핸드오프는 버렸다. 첫 발화와 마지막 마무리 발화는
**채점하지 않는다** — 그래서 최종 112편에서 MOD 발화 1,295개 중 채점 대상은 1,071개다.

### 기준 3 — 진행자가 편을 들지 않고 할 수 있는가

분석 ②의 네거티브 클래스가 여기서 쓰인다.
대법원 재판장의 41.4%가 본안 참여였다. 우리는 그걸 실패로 정의했다.

**탈락**: `Press debaters for direct answers and correct errors` **8,047 (25.8%)** 전부.
두 번째로 큰 최상위 군집을 통째로 버린 것이다. 하위를 보면 이유가 분명하다 —
"counter-evidence를 들이대며 반박을 요구한다", "사실 오류를 정정한다",
"가설 반례로 일관성을 시험한다". 전부 진행자가 **한쪽 편에 서서** 하는 행동이다.
Donvan 스타일에서는 자연스럽지만, 우리가 만들려는 건 PMQs 의장이다.

### 남은 것 = 최종 9개

기준 세 개를 통과한 것은 최대 군집 `Manage debate flow and transitions` 15,492(49.6%)의
내부와, `Clarify scope and redirect` 하위의 `Redirect to the original question` 1,296뿐이다.
여기에 내용 개입 중 **유일하게 중립으로 판정 가능한 하나**를 추가했다.

| 최종 코드 | 근거가 된 군집·무브 |
|---|---|
| **A1** 초과 발화 강제 중단 (넘길 사람 없음) | Interrupt and yield the floor 2,502 · M14 · 7+1 C |
| **A2-1** 끊고 상대측에 넘김 | Enforce time limits and transition to next speaker 866 · M04 · ③B1 |
| **A2-2** 마무리 후 넘김 | Transition to the next speaker 1,303 + Assign speaking turns 2,227 · M04 16.5% · ④#1 21.7% |
| **A3-1** 크로스파이어 개시 | M17 라운드 전환 · Munk A3-1 6.0% |
| **A3-2** 클로징 개시 | Transition to Closing Statements 179 · M18 4.0% · ④#23 |
| **A4** 10초 고지 | Count down remaining time 24 · M14 3.7% · ③C1 3.3% · 7+1 C |
| **A5** 끼어들기 차단·발언권 보호 | Enforce turn-taking by stopping simultaneous speech 717 · M12 6.1% · ③B2 5.3% · **7+1 B (PMQs 34.9%)** |
| **B1** 논제 복귀 | Redirect to the original question 1,296 · M13 1.0% · ③E2 1.5% · 7+1 D |
| **B2** 자기모순 지적 | ①M10 계열에서 재정의. 아래 설명 |

### B2는 데이터에서 군집으로 올라오지 않았다

정직하게 적어야 할 부분이다. 자기모순 지적은 어느 분석에서도 **독립 군집으로
나오지 않았다**. ①의 M10(답변 회피 압박) 1.4%가 가장 가까운 항목이다.

그런데도 넣은 이유는 이것이 **내용 개입 중 유일하게 편을 안 들고 할 수 있는 행동**이기
때문이다. 진행자는 두 발언을 나란히 놓고 "어느 쪽입니까"라고 물을 뿐 판정하지 않는다.
누가 옳은지 말하지 않으므로 기준 3을 통과하고,
"같은 화자의 양립 불가능한 두 주장"은 관찰 가능하므로 기준 1도 통과한다.

그리고 최종 라벨링(§9)에서 **실제로 691건(2.2%)** 이 확인됐다.
군집의 머리로 뜰 만큼 흔하지는 않지만, 실제 진행자가 하기는 하는 행동이다.

### 10개에서 9개로 — B2-1과 B2-2의 통합

7월 라벨링 시점의 분류 체계는 **10개**였다. B2가 둘로 갈려 있었다.

- `B2-1` 오프닝에서 한 말과 크로스파이어 발언이 충돌 (긴 사거리)
- `B2-2` 크로스파이어 안에서 앞뒤 발언이 충돌 (짧은 사거리)

사거리를 나눈 건 난이도가 다르기 때문이다. 긴 사거리는 모델이 3분 전을 기억해야 풀린다.
그런데 실제 코퍼스 분포가 `B2-1` 0.6% / `B2-2` 1.6%로 둘 다 희소했고,
gen2 생성 단계에서 사거리는 **생성 파라미터**로 다루고 코드는 하나로 합치는 편이
시드 뱅크 운용에 유리했다. 그래서 벤치마크 코드는 `B2` 하나다.
최종 112편의 B2 트리거 64건은 **전부 크로스파이어 내부**(옛 B2-2)로 실현됐다.

**10 → 9가 된 지점이 여기다.**

---

## 9. 검증 — 31,264 윈도우 전수 라벨링 (2026-07-25 ~ 26)

고른 코드가 실제 코퍼스에서 얼마나 잡히는지 전수로 확인했다.

**설정**: `Qwen/Qwen3.5-122B-A10B-FP8`, vLLM TP=2, pro6000 ×2.
JSON 스키마로 label을 enum 제약해 **파싱 실패 0건**.
스크립트 `_meta/label/label_taxonomy.py`, 출력 `_meta/label/out/labels.jsonl`.

**프롬프트 3회 반복**이 필요했다(첫 2,000 IQ2 윈도우로 검증).

| 버전 | 문제 | 수정 |
|---|---|---|
| v1 | 희소 코드를 남발. 투표 낭독→A1, 466단어 프레이밍→A4, 이름만 "Jim Grant."→B2-1. `no`를 잘 안 씀 | — |
| v2 | `no` 22% → 40% | `## Rules` 추가: 표시된 턴에 트리거가 **정확히** 있을 때만 코드 사용 / MOD가 **말한 것**만 판정 / 이름 한 마디나 한 줄짜리는 절대 B 코드 아님 / 애매하면 `no` |
| v3 | JSON 잘림 0.2% | "A4는 짧은 끼어들기이지 긴 독백이 아니다" 추가 + max_tokens 160→256, `reason` 220자 제한 |

**최종 분포 (31,264건)**

| 라벨 | 건수 | 비율 |
|---|---:|---:|
| `no` | 14,740 | 47.1% |
| A2-2 | 4,345 | 13.9% |
| A2-1 | 4,207 | 13.5% |
| B1 | 3,112 | 10.0% |
| A5 | 2,094 | 6.7% |
| A3-1 | 811 | 2.6% |
| A4 | 532 | 1.7% |
| A3-2 | 511 | 1.6% |
| B2-2 | 488 | 1.6% |
| A1 | 221 | 0.7% |
| B2-1 | 203 | 0.6% |

A/B/no = 40.6 / 12.1 / 47.1%.

**코퍼스별 커버리지**: IQ2 62.7% · Munk 60.0% · Doha 48.6% · OpenToDebate 47.5%.
IQ2가 높은 건 우리 분류 체계가 옥스퍼드식 라운드 형식을 전제하기 때문이다.
Doha·OTD는 형식이 느슨해 `no`가 많다.

**이 결과가 말해주는 것**

1. **9개가 실제 진행자 행동의 40.6%를 덮는다.** 나머지 47.1%는 환영·프레이밍·
   투표 낭독·맞장구 등 기준 1~3에서 의도적으로 버린 것들이다. 설계대로다.
2. **A1이 가장 희소하다(0.7%).** 실제 4인 토론에는 항상 다음 발언자가 있어서
   "끊고 끝"이 드물다. 우리 3인 형식에서는 각 라운드 마지막 발언자에게
   넘길 상대가 없으므로 A1이 **구조적으로 필연**이 된다. 자연 분포와 우리 형식이
   갈리는 지점이고, 그래서 A1은 벤치마크에서 선택 코드다.
3. **A4가 1.7%로 작다.** 실제 진행자는 시간 고지를 자주 하지 않는다.
   우리는 20초 규격 때문에 필수로 만들었다. 한계 절에 적어야 한다.

---

## 10. 분류 체계에서 벤치마크로

라벨링 결과가 **시드 뱅크의 원천 풀**이 된다. 진행자 대사는 LLM이 쓰지 않는다.

```
labels.jsonl (31,264)
  → 두 번 라벨링해 일치하는 것만 채택          6,889
  → 코드당 최대 300, 이름·논제를 [PRO]/[CON]/[MOTION] 태그로 치환   2,424 후보
  → 3인 리뷰 웹앱 (±6턴 맥락, pass/fail)        300 검수 완료
  → gen2 시드 뱅크                              3,320
  → LLM 게이트 + 장면 추출                        627 장면 시드
```

LLM 게이트가 거르는 것: 코드 불일치 / 외부 맥락 필요 / 청중·투표·패널 언급 /
문장 조각 / 10초가 아닌 시간 / 한 턴에 두 가지 일.
A5는 **누구를 막고 누구에게 넘기는지**가 발화에 드러나야 한다(272 → 222).

최종 627 장면 시드 분포: A3-2 148 · A3-1 115 · A2-2 99 · A5 93 · A1 45 · A4 38 ·
B1 37 · A2-1 28 · B2 24. 출처는 IQ2 247 · OTD 227 · Doha 124 · Munk 9 · 합성 20.

**B2가 24개로 가장 적다.** 자기모순 시드는 두 주장이 **논리적으로 양립 불가**해야 하는데
(조건 추가·범위 축소는 모순이 아니다) 그 조건을 만족하는 실제 사례가 드물다.
최종 112편에서 B2 64건은 이 24개 프레임을 재사용해 만들어졌다.

---

## 11. 최종 9코드

| 코드 | 행동 | 단계 | 필수/선택 |
|---|---|---|---|
| **A1** | 시간 초과 발화를 끊는다 (넘길 다음 발언자 없음) | 1, 3 | 선택 |
| **A2-1** | 초과 발화를 끊고 상대측에 넘긴다 | 1, 3 | 선택 |
| **A2-2** | 시간 안에 끝난 발화 뒤 상대측을 부른다 | 1, 3 | 필수 |
| **A3-1** | 오프닝을 닫고 크로스파이어를 연다 (길이·시작점 고지) | 1→2 | 필수 |
| **A3-2** | 크로스파이어를 끊고 클로징을 연다 | 2→3 | 필수 |
| **A4** | "10초 남았습니다" — 끊지 않고 겹쳐서 알린다 | 전 구간 | 필수 |
| **A5** | 차례 아닌 쪽의 끼어들기를 막고 발언권을 돌려준다 | 1, 3 | 선택 |
| **B1** | 논제를 벗어난 발언을 되돌린다 | 2 | 선택 |
| **B2** | 같은 화자의 양립 불가능한 두 주장을 짚고 되묻는다 | 2 | 선택 |

**A = 시간·발언권**, **B = 내용**. B는 크로스파이어에서만 나온다.

최종 벤치마크 112편의 트리거 1,071개:
A4 278 · A4(크로스파이어) 112 · A2-2 166 · A3-1 112 · A3-2 112 ·
B2 64 · A1 59 · A2-1 58 · B1 57 · A5 53.

---

## 12. 한계 (논문 Limitations에 그대로 쓸 것)

1. **A4 필수화가 자연 분포와 다르다.** 실제 진행자의 시간 고지는 1.7%뿐이고,
   30초를 넘겨도 사전 고지 없이 끊는 경우가 많다. 우리 규칙은 A1/A2-1 앞에
   반드시 A4가 오도록 강제한다. 논리적으로는 맞지만 실제 관행은 아니다.
2. **A1은 우리 형식이 만들어낸 코드다.** 4인 토론에서는 거의 나오지 않는다(0.7%).
3. **B2는 군집으로 올라오지 않았다.** 기준 3을 만족하는 유일한 내용 개입이라
   설계로 넣은 것이고, 코퍼스에는 2.2%로 존재한다.
4. **분류 체계가 IQ2 편향이다.** 코퍼스별 커버리지가 IQ2 62.7% vs OTD 47.5%로 갈린다.
   ①의 21-move 자체가 John Donvan 한 사람의 스타일에서 나왔다.
5. **시드 검수가 미완이다.** 3인 리뷰는 300건에서 멈췄고 A3-1/A3-2/A4는 통과 수가 적다.
6. **라벨링이 LLM 단일 판정이다.** 사람 교차검증은 ②의 95턴 표본(92.6% 일치)뿐이다.

---

## 13. 파일 위치

| 무엇 | 경로 |
|---|---|
| 윈도우 추출 | `_meta/openclio/extract_windows_all.py` |
| 공통 입력 31,264 | `_meta/openclio/input/all.jsonl` |
| ① IQ2 21-move | `datasets/A1_IQ2_IntelligenceSquared/MODERATOR_TAXONOMY.md` |
| ② 의회·대법원 7+1 | `/home/dongwook_lee/ICLR2027/Moderator_Taxonomy.md`, `_meta/taxonomy_labeling_result.json` |
| ③ 연역적 5×2 | `_meta/llm_label/classify_moderator.py`, `output/classify_stats.md` |
| ④ k-means K=25 | `_meta/llm_label/kmeans_label.py`, `output/kmeans_stats.md` |
| ⑤ OpenClio 실행 | `_meta/openclio/run_openclio.py`, `run_openclio_all.sbatch` |
| ⑤ 결과 트리 | `_meta/openclio/out/all/hierarchy.{txt,json}`, `hierarchy_full.txt` (예문 포함) |
| ⑤ 대화형 HTML | `_meta/openclio/out/all/clio_all/index.html` |
| 전수 라벨링 | `_meta/label/label_taxonomy.py`, `out/labels.jsonl` |
| 프롬프트 v1/v2 백업 | `_meta/label/out/labels_v1_oldprompt.jsonl`, `labels_v2.jsonl` |
| 최종 분류 체계 (한글) | `TAXONOMY.md` |
| 최종 분류 체계 (영문, 10코드판) | `moderator-taxonomy (1).md` |
| 생성 규칙과 근거 | `_meta/gen2/RULES_AND_WHY.md`, `DEBATE_SPEC.txt` |
| 시드 뱅크 | `_meta/gen2/assets/seedbank.json` (3,320), `scenebank.json` (627) |
| 논문 초안 | `_meta/gh_repo/history.md` |

`hierarchy_full.txt`에는 각 말단 군집의 **실제 발화 예문**이 붙어 있다.
논문에 군집 예시를 넣을 때 여기서 가져오면 된다.

재현하려면 `run_openclio_all.sbatch`를 그대로 제출하면 된다.
입력 `all.jsonl`과 모델이 로컬에 있으므로 추가 준비는 없다.

---

## 부록 — 영문 요약 (논문 붙여넣기용)

> We did not adopt an existing moderator taxonomy. Existing schemes are built for
> text-based argument analysis and omit timing, which is the core of a full-duplex
> moderator's job. We instead induced the action space from data and then narrowed it
> by what our three-speaker format can support.
>
> Five independent analyses were run over four moderated policy-debate corpora
> (IQ2, Open to Debate, Doha, Munk; 366 debates, 31,264 moderator windows, each window
> a moderator turn with four turns of context on either side): a hand-built 21-move
> inventory labelled on a 2,050-turn stratified sample of IQ2; a 7+1 action space
> labelled over all 1,878 chair turns of UK PMQs and US Supreme Court oral argument;
> a deductive 5x2 scheme applied to all 10,192 IQ2 moderator turns; k-means (K=25) over
> 6,087 free-text action labels; and a bottom-up OpenClio clustering of all 31,264 windows
> on a single "ModeratorAction" facet.
>
> All five converge: floor allocation dominates. The largest OpenClio cluster,
> "Manage debate flow and transitions", holds 15,492 of 31,224 clustered points (49.6%),
> and the same move ranks first in every other analysis (bare-name handoff 16.5%;
> turn-order guidance 46.4%; "introduce and call on next speaker" 21.7%).
> The second largest cluster, "Press debaters for direct answers and correct errors"
> (8,047, 25.8%), is the moderator arguing the merits.
>
> Three filters produced the final set. (i) The format must decide right from wrong:
> this removes clarification and follow-up questioning (4,283, 13.7%), where many
> different moves are equally correct. (ii) The move must exist with three speakers and
> no audience: this removes audience Q&A and polls (2,451, 7.8%), vote and winner
> announcements (1,341, 4.3%), and broadcast banter (951, 3.0%). (iii) The moderator must
> not take a side: the Supreme Court analysis showed 41.4% of a Chief Justice's turns are
> substantive participation, which we define as failure, and this removes the entire
> second-largest cluster (8,047, 25.8%).
>
> What survives is the interior of the flow cluster plus one redirect move, giving
> seven floor-and-time codes (A1, A2-1, A2-2, A3-1, A3-2, A4, A5) and two content codes
> (B1 back-to-motion, B2 self-contradiction). B2 did not emerge as a cluster; it was
> added as the only content intervention a neutral chair can make without ruling, and it
> appears in 2.2% of real moderator turns. Labelling all 31,264 windows against the final
> scheme with a 122B model under a JSON-constrained decoder (zero parse errors) assigns a
> code to 40.6% of real moderator turns, with the remainder falling into the categories
> the three filters deliberately excluded.

