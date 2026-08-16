# Moderator taxonomy reference

## 빠른 표

| 코드 | 한국어 이름 | 필요한 선행 상황 | MOD action | 기본 오디오 관계 |
|---|---|---|---|---|
| A1 | 시간 초과 강제 종료 | deadline이 지났는데 같은 화자가 계속 말함 | 발화를 짧게 종료 | MOD가 진행 중 발화에 barge-in |
| A2-1 | 시간 초과 발화를 끊고 상대에게 넘김 | deadline 초과 + 다음 화자에게 floor 이전 필요 | 현재 화자를 멈추고 상대 호출 | MOD barge-in 후 다음 화자 시작 |
| A2-2 | 자연스럽게 끝난 뒤 상대에게 넘김 | 현재 화자가 시간 안에 완결 | 다음 화자 호출 | overlap 없는 순차 handoff |
| A3-1 | 자유토론 시작 | PRO와 CON opening 완료 | Round 2 직접 토론 개시 | overlap 없는 phase transition |
| A3-2 | 자유토론 종료·마무리 시작 | direct debate 시간 종료 | Round 3 시작, 반드시 PRO 먼저 호출 | 보통 순차 transition |
| A4 | 남은 시간 고지 | 현재 화자에게 약 10초 남음 | 짧은 시간 안내 | MOD가 현재 화자 위에 overlap |
| A5 | 발언권 보호 | 상대가 floor holder를 가로챔 | interrupter를 막고 floor 복구 | 두 토론자 overlap 후 MOD 개입 |
| B1 | 논제 이탈 교정 | 발언이 motion 핵심 질문에서 이탈 | motion으로 redirect | 보통 이탈 발화 뒤 순차 개입 |
| B2 | 자기모순 지적 | 같은 화자가 양립하기 어려운 두 주장 발화 | 두 주장을 정확히 대조 | 두 claim 뒤 순차 개입 |

## A1 — 시간 초과 강제 종료

필수 조건:

- Event에 명시된 deadline이 있어야 한다.
- Floor holder의 발화가 deadline 뒤에도 계속되어야 한다.
- MOD는 deadline 이후, floor holder가 끝나기 전에 시작한다.
- MOD는 종료만 수행한다. 다음 화자를 호출하면 A2-1이다.

적절한 예: `Time.` / `Your time is up. Thank you, Daniel.`

부적절한 예: 발화자가 이미 끝난 뒤 `Time.`이라고 말함.

## A2-1 — 시간 초과 발화를 끊고 상대에게 넘김

필수 조건:

- A1의 초과 조건을 모두 만족한다.
- MOD utterance가 상대 토론자를 명시적으로 호출한다.
- 호출된 상대가 다음 substantive floor를 가져간다.

적절한 예: `I have to stop you there. Sarah, your response.`

## A2-2 — 자연스러운 handoff

필수 조건:

- 현재 발화는 deadline 안에서 의미상 완결된다.
- MOD와 앞 발화가 겹치지 않는다.
- MOD가 상대를 호출하고 그 상대가 다음에 말한다.

적절한 예: `Thank you, Daniel. Sarah, your opening statement.`

## A3-1 — 자유토론 시작

필수 조건:

- Phase 1에 PRO와 CON opening이 모두 존재한다.
- A3-1 MOD turn은 Phase 2의 첫 turn이다.
- 이후 PRO 또는 CON이 상대 주장에 직접 반응한다.
- 청중 화자가 없다면 audience question을 예고하지 않는다.

권장 문구: `That concludes round one. We now move to round two, where the debaters address one another directly.`

## A3-2 — 마무리 발언 시작

필수 조건:

- 앞에 Phase 2 direct debate가 존재한다.
- A3-2 MOD turn은 Phase 3의 첫 turn이다.
- 첫 closing speaker는 항상 PRO다.
- CON closing은 PRO 뒤에 온다.

## A4 — 남은 시간 고지

필수 조건:

- MOD 시작 시점부터 floor holder 종료 시점까지 8–12초가 남아야 한다.
- MOD utterance는 10단어 이하다.
- MOD와 현재 floor holder가 실제 시간축에서 겹친다.
- MOD는 floor를 빼앗거나 다음 화자를 호출하지 않는다.
- Floor holder는 안내 뒤에도 같은 발언을 이어간다.

적절한 예: `Ten seconds, Daniel.`

A4와 A5의 차이: A4는 MOD가 현재 화자 위에 시간 안내를 얹는다. A5는 먼저 두 토론자가
서로 겹치고, MOD가 발언권을 복구한다.

## A5 — 발언권 보호

필수 조건:

- 한 토론자가 floor를 보유한다.
- 반대 토론자의 12단어 이하 짧은 발화가 floor holder와 겹친다.
- MOD는 interrupter가 끝나기 전 또는 끝난 직후 0.5초 안에 개입한다.
- MOD는 원래 floor holder를 명시적으로 보호한다.

적절한 예: `Let Sarah finish, please.`

## B1 — 논제 이탈 교정

필수 조건:

- Trigger 발화는 직전 논거에서 자연스럽게 시작하지만 motion 판단과 무관한 곁가지로 이탈한다.
- MOD는 이탈 내용을 지어내지 않고 motion의 핵심 질문으로 되돌린다.
- 지나치게 노골적인 `I want to change the subject` 문장은 planted trigger로 보일 수 있으므로 피한다.

자동 검사는 linkage와 순서만 보장한다. 실제 이탈인지는 transcript-only semantic review가 필요하다.

## B2 — 자기모순 지적

필수 조건:

- CLAIM_A와 CLAIM_B는 같은 non-MOD speaker의 직접 발화다.
- 두 claim 모두 MOD action 전에 존재한다.
- Event의 quote가 실제 trigger text에 그대로 포함된다.
- 단순한 조건 추가, 범위 축소, 불확실성 표현을 모순으로 만들지 않는다.
- MOD는 상대의 비판이나 paraphrase가 아니라 원 화자의 두 주장을 대조한다.

자동 검사는 same-speaker, quote grounding과 순서를 보장한다. 논리적 비양립성은 transcript-only
semantic review가 필요하다.
