# Taxonomy example catalog

아래 9개 fixture는 각 taxonomy의 선행 trigger, MOD action, 결과와 한국어 해석을 보여준다.
표시된 PASS는 deterministic structural/timing validation이며 human correctness가 아니다.
B1과 B2는 별도 semantic review가 필요하다.

# a1_time_stop_example

- Mode: `event-window`
- Motion: **Schools should replace printed textbooks with tablets.**
- Target: A1
- Automatic validation: **PASS**
- Timeline span: 13.000s
- Maximum turn rate: 240.000 WPM (`t002`; ceiling 260 WPM)

## Events

| Taxonomy | MOD turn | Trigger turns |
|---|---|---|
| A1 | `t002` | `t001` |

## Transcript

**PRO / Daniel** `t001` `0.00–9.20s`

Tablets can update material quickly, reduce the weight students carry, and make diagrams interactive, so schools should treat them as the main learning tool.

> **한국어 해석:** 태블릿은 자료를 빠르게 갱신하고 학생들이 들고 다니는 무게를 줄이며 도표를 상호작용형으로 만들 수 있으므로, 학교는 이를 주요 학습 도구로 사용해야 합니다.

**MOD / Alice** `t002` `8.10–9.10s` **[A1]**

Time. Thank you, Daniel.

> **한국어 해석:** 시간입니다. Daniel, 고맙습니다.

**CON / Sarah** `t003` `9.50–13.00s`

The convenience does not remove concerns about distraction and unequal access.

> **한국어 해석:** 그런 편리함이 산만함과 접근성 격차에 대한 우려를 없애지는 않습니다.

---

# a2_1_overtime_handoff_example

- Mode: `event-window`
- Motion: **Cities should make public transportation free.**
- Target: A2-1
- Automatic validation: **PASS**
- Timeline span: 16.100s
- Maximum turn rate: 225.000 WPM (`t002`; ceiling 260 WPM)

## Events

| Taxonomy | MOD turn | Trigger turns |
|---|---|---|
| A2-1 | `t002` | `t001` |

## Transcript

**PRO / Daniel** `t001` `0.00–10.50s`

Free transit would expand access to work, reduce car traffic, and make the network useful to more residents, especially when service is frequent.

> **한국어 해석:** 대중교통을 무료로 만들면 일자리 접근성이 확대되고 자동차 교통량이 줄며, 특히 운행 간격이 짧을 때 더 많은 주민이 교통망을 이용하게 됩니다.

**MOD / Alice** `t002` `8.20–10.60s` **[A2-1]**

I have to stop you there. Sarah, your response.

> **한국어 해석:** 여기서 멈춰야겠습니다. Sarah, 답변해주세요.

**CON / Sarah** `t003` `10.80–16.10s`

Removing fares does not solve unreliable service, and the lost revenue could make frequency worse.

> **한국어 해석:** 요금을 없애도 불안정한 운행 문제는 해결되지 않으며, 수입 감소로 운행 횟수가 더 줄어들 수 있습니다.

---

# a2_2_natural_handoff_example

- Mode: `event-window`
- Motion: **Remote work should be the default for office jobs.**
- Target: A2-2
- Automatic validation: **PASS**
- Timeline span: 14.500s
- Maximum turn rate: 254.545 WPM (`t002`; ceiling 260 WPM)

## Events

| Taxonomy | MOD turn | Trigger turns |
|---|---|---|
| A2-2 | `t002` | `t001` |

## Transcript

**PRO / Daniel** `t001` `0.00–7.00s`

Remote work saves commuting time and lets employees organize focused work around clear goals. That is my central reason for supporting the motion.

> **한국어 해석:** 원격 근무는 통근 시간을 절약하고 직원들이 명확한 목표에 맞춰 집중 업무를 구성하게 해줍니다. 이것이 제가 논제에 찬성하는 핵심 이유입니다.

**MOD / Alice** `t002` `7.30–8.95s` **[A2-2]**

Thank you, Daniel. Sarah, your opening statement.

> **한국어 해석:** Daniel, 고맙습니다. Sarah, 최초 발언을 해주세요.

**CON / Sarah** `t003` `9.00–14.50s`

A default must work for new employees and collaborative teams, not only for experienced workers with quiet homes.

> **한국어 해석:** 기본 원칙이라면 조용한 집이 있는 숙련 직원뿐 아니라 신입 직원과 협업 팀에도 효과가 있어야 합니다.

---

# a3_1_round_two_start_example

- Mode: `event-window`
- Motion: **Video games will make us smarter.**
- Target: A3-1
- Automatic validation: **PASS**
- Timeline span: 25.600s
- Maximum turn rate: 255.000 WPM (`t003`; ceiling 260 WPM)

## Events

| Taxonomy | MOD turn | Trigger turns |
|---|---|---|
| A3-1 | `t003` | `t001`, `t002` |

## Transcript

**PRO / Daniel** `t001` `0.00–5.00s`

Games can strengthen planning because players repeatedly test choices, receive feedback, and revise strategies.

> **한국어 해석:** 게임은 플레이어가 선택을 반복해서 시험하고 피드백을 받아 전략을 수정하게 하므로 계획 능력을 강화할 수 있습니다.

**CON / Sarah** `t002` `5.40–10.40s`

Skill inside one game does not necessarily transfer to careful reasoning outside that designed system.

> **한국어 해석:** 한 게임 안의 능력이 그 설계된 체계 밖의 신중한 추론으로 반드시 전이되는 것은 아닙니다.

**MOD / Alice** `t003` `10.80–14.80s` **[A3-1]**

That concludes round one. We now move to round two, where the debaters address one another directly.

> **한국어 해석:** 이것으로 1라운드를 마칩니다. 이제 토론자들이 서로에게 직접 답하는 2라운드로 넘어가겠습니다.

**PRO / Daniel** `t004` `15.10–19.60s`

Sarah, why should feedback-driven planning stop being useful when the screen is gone?

> **한국어 해석:** Sarah, 화면이 사라지면 피드백에 기반한 계획 능력이 왜 더 이상 유용하지 않다고 보십니까?

**CON / Sarah** `t005` `19.90–25.60s`

Because transfer requires recognizing the same structure in a new context, and a score does not prove that recognition.

> **한국어 해석:** 전이되려면 새로운 맥락에서 같은 구조를 알아봐야 하는데, 점수만으로는 그런 인식을 입증할 수 없기 때문입니다.

---

# a3_2_closing_start_example

- Mode: `event-window`
- Motion: **Schools should start later in the morning.**
- Target: A3-2
- Automatic validation: **PASS**
- Timeline span: 24.900s
- Maximum turn rate: 260.000 WPM (`t003`; ceiling 260 WPM)

## Events

| Taxonomy | MOD turn | Trigger turns |
|---|---|---|
| A3-2 | `t003` | `t001`, `t002` |

## Transcript

**PRO / Daniel** `t001` `0.00–5.00s`

A later start gives students a schedule that better supports attention during first-period classes.

> **한국어 해석:** 등교 시간을 늦추면 학생들이 1교시 수업에 더 집중할 수 있는 일정을 만들 수 있습니다.

**CON / Sarah** `t002` `5.40–10.20s`

It can also shift transportation, sports, and family schedules in ways schools cannot ignore.

> **한국어 해석:** 그러나 교통, 운동 활동, 가족 일정도 뒤로 밀릴 수 있으며 학교는 이를 무시할 수 없습니다.

**MOD / Alice** `t003` `10.60–13.60s` **[A3-2]**

That concludes round two. Daniel, please give the closing statement for the motion.

> **한국어 해석:** 이것으로 2라운드를 마칩니다. Daniel, 논제에 찬성하는 마무리 발언을 해주세요.

**PRO / Daniel** `t004` `13.90–18.90s`

Schools exist for learning, so schedules should put student alertness at the center of the decision.

> **한국어 해석:** 학교는 학습을 위해 존재하므로 일정 결정의 중심에는 학생들의 각성 상태가 있어야 합니다.

**CON / Sarah** `t005` `19.30–24.90s`

A uniform later start can create new burdens, so local schools need flexibility rather than a blanket rule.

> **한국어 해석:** 일률적으로 늦게 시작하면 새로운 부담이 생길 수 있으므로 포괄적인 규칙보다 지역 학교의 유연성이 필요합니다.

---

# a4_ten_second_notice_example

- Mode: `event-window`
- Motion: **Public libraries should eliminate late fees.**
- Target: A4
- Automatic validation: **PASS**
- Timeline span: 19.000s
- Maximum turn rate: 225.000 WPM (`t002`; ceiling 260 WPM)

## Events

| Taxonomy | MOD turn | Trigger turns |
|---|---|---|
| A4 | `t002` | `t001` |

## Transcript

**PRO / Daniel** `t001` `0.00–15.00s`

Late fees can discourage people who most need library access, while reminders and temporary borrowing limits can still encourage returns without creating debt.

> **한국어 해석:** 연체료는 도서관 접근이 가장 필요한 사람들의 이용을 막을 수 있으며, 알림과 일시적인 대출 제한만으로도 빚을 만들지 않고 반납을 유도할 수 있습니다.

**MOD / Alice** `t002` `5.00–5.80s` **[A4]**

Ten seconds, Daniel.

> **한국어 해석:** Daniel, 10초 남았습니다.

**CON / Sarah** `t003` `15.40–19.00s`

Libraries still need a fair way to keep shared materials circulating.

> **한국어 해석:** 도서관에는 공유 자료가 계속 순환하도록 만드는 공정한 방법이 여전히 필요합니다.

---

# a5_floor_protection_example

- Mode: `event-window`
- Motion: **Video games will make us smarter.**
- Target: A5
- Automatic validation: **PASS**
- Timeline span: 11.000s
- Maximum turn rate: 257.143 WPM (`t002`; ceiling 260 WPM)

## Events

| Taxonomy | MOD turn | Trigger turns |
|---|---|---|
| A5 | `t003` | `t001`, `t002` |

## Transcript

**CON / Sarah** `t001` `0.00–5.50s`

The benefit depends on reflection, because repeating a rewarded move does not by itself show that the player understands the reason.

> **한국어 해석:** 보상받는 행동을 반복하는 것만으로는 플레이어가 그 이유를 이해한다고 볼 수 없으므로, 이점은 성찰에 달려 있습니다.

**PRO / Daniel** `t002` `4.20–5.60s`

But feedback can teach that reason.

> **한국어 해석:** 하지만 피드백이 그 이유를 가르칠 수 있습니다.

**MOD / Alice** `t003` `4.80–6.00s` **[A5]**

Let Sarah finish, please.

> **한국어 해석:** Sarah가 마저 말하게 해주세요.

**CON / Sarah** `t004` `6.20–11.00s`

Thank you. Feedback helps only when the player can explain what changed and apply it elsewhere.

> **한국어 해석:** 고맙습니다. 피드백은 플레이어가 무엇이 바뀌었는지 설명하고 다른 곳에 적용할 수 있을 때만 도움이 됩니다.

---

# b1_topic_redirect_example

- Mode: `event-window`
- Motion: **Video games will make us smarter.**
- Target: B1
- Automatic validation: **PASS**
- Timeline span: 17.600s
- Maximum turn rate: 257.143 WPM (`t003`; ceiling 260 WPM)
- Semantic warnings: B1 requires transcript-only semantic review for genuine topic drift

## Events

| Taxonomy | MOD turn | Trigger turns |
|---|---|---|
| B1 | `t003` | `t002` |

## Transcript

**PRO / Daniel** `t001` `0.00–4.00s`

Good design can expose tradeoffs and ask players to revise a failed plan.

> **한국어 해석:** 좋은 설계는 상충하는 선택을 보여주고 실패한 계획을 수정하도록 요구할 수 있습니다.

**CON / Sarah** `t002` `4.40–10.50s`

Design matters in other ways too. A beautiful soundtrack can make a difficult level memorable, and players often value that atmosphere.

> **한국어 해석:** 설계는 다른 면에서도 중요합니다. 아름다운 배경음악은 어려운 레벨을 기억에 남게 하며, 플레이어들은 종종 그런 분위기를 중요하게 여깁니다.

**MOD / Alice** `t003` `10.80–12.90s` **[B1]**

Let's return to whether video games make us smarter.

> **한국어 해석:** 비디오 게임이 우리를 더 똑똑하게 만드는지로 돌아가겠습니다.

**CON / Sarah** `t004` `13.20–17.60s`

A memorable atmosphere does not demonstrate better reasoning, so transfer still has to be shown.

> **한국어 해석:** 기억에 남는 분위기가 더 나은 추론을 입증하지는 않으므로, 전이 효과는 여전히 입증되어야 합니다.

---

# b2_self_contradiction_example

- Mode: `event-window`
- Motion: **Video games will make us smarter.**
- Target: B2
- Automatic validation: **PASS**
- Timeline span: 25.900s
- Maximum turn rate: 258.824 WPM (`t004`; ceiling 260 WPM)
- Semantic warnings: B2 requires transcript-only semantic review for logical incompatibility

## Events

| Taxonomy | MOD turn | Trigger turns |
|---|---|---|
| B2 | `t004` | `t001`, `t003` |

## Transcript

**CON / Sarah** `t001` `0.00–5.00s`

Games can improve people's planning and communication beyond play, even if the amount of transfer varies.

> **한국어 해석:** 전이 정도에는 차이가 있더라도 게임은 게임 밖에서 사람들의 계획 능력과 의사소통 능력을 향상시킬 수 있습니다.

**PRO / Daniel** `t002` `5.40–9.50s`

Then you accept that at least some game-based practice can make people better reasoners.

> **한국어 해석:** 그렇다면 적어도 일부 게임 기반 연습이 사람들을 더 나은 추론자로 만들 수 있다는 점은 인정하는군요.

**CON / Sarah** `t003` `9.90–15.00s`

Games do not improve people's planning or communication at all; those skills are only exercised inside the game.

> **한국어 해석:** 게임은 사람들의 계획 능력이나 의사소통 능력을 전혀 향상시키지 않습니다. 그런 능력은 게임 안에서 연습될 뿐입니다.

**MOD / Alice** `t004` `15.30–20.40s` **[B2]**

You said games improve those skills beyond play, but now you say they do not improve them at all. Which is it?

> **한국어 해석:** 게임이 그런 능력을 게임 밖에서도 향상시킨다고 했는데, 이제는 전혀 향상시키지 않는다고 말하고 있습니다. 어느 쪽입니까?

**CON / Sarah** `t005` `20.70–25.90s`

I need to revise my first claim: games may exercise those skills, but transfer beyond play is not established.

> **한국어 해석:** 첫 주장을 수정해야겠습니다. 게임이 그런 능력을 연습시킬 수는 있지만, 게임 밖으로의 전이는 입증되지 않았습니다.

---
