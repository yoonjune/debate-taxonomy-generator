# Bounded loop and validation

## Why use a loop

Generation regularly misses exact timing, overlap, event linkage, same-speaker B2 grounding, or closing order.
A bounded loop is useful for mechanical correction. An unbounded loop is not useful because it can tune the
prompt and sample to each other and hide failure.

## Loop contract

```text
freeze assignment
→ generate JSON
→ run deterministic validator
→ repair only reported failures
→ rerun validator
→ transcript-only semantic review
→ at most one local semantic repair
→ final validation and render
```

Limits:

- Event-window: maximum 2 validator repairs.
- Full-debate development sample: maximum 3 validator repairs.
- Frozen/share sample: maximum 2 validator repairs.
- Full regeneration: maximum 1.
- Stop and report failure when limits are exhausted.

Immutable during the loop:

- requested taxonomy
- motion
- participant roles
- mode and duration profile
- contract and acceptance thresholds
- seed provenance

## Automatic validation

Event-window에서는 `scripts/validate_sample.py`를 실행한다. Full-debate에서는
`references/full-debate.md`에 지정된 WPM validator를 실행한다. Full-debate를 event-window validator로
통과시켜서는 안 된다.

Event-window validator는 다음을 검사한다.

- schema, roles, unique turn IDs, timestamps, translations
- turn별 260 WPM ceiling
- 같은 화자의 중복 turn overlap
- taxonomy target/event/MOD-turn linkage
- trigger-before-action ordering
- phase transitions and PRO-first closing
- A1/A2 deadline and handoff structure
- A4 remaining-time and MOD overlap
- A5 floor/interrupter overlap and prompt intervention
- B2 same-speaker quotes and grounding

## Semantic review

Automatic validation cannot decide all meaning. Read transcript without generation rationale and check:

- B1 is genuine topic drift rather than an inserted nonsense sentence.
- B2 claims are logically incompatible rather than qualification or scope change.
- MOD paraphrases only visible claims.
- Both sides remain comparably strong and responsive.
- MOD is neutral and does not invent time, agenda, facts, or floor ownership.

Label the result `automatic PASS` and `semantic review PASS` separately. Same-family model review is not human
validation. Keep it provisional until a person reviews it.

## Regression suite

Run:

```bash
python3 skills/generate-debate-taxonomy/scripts/validate_examples.py
```

The suite must contain one positive fixture and at least one targeted negative mutation per taxonomy. Global
negative cases additionally confirm duplicate same-speaker intervals fail. Negative cases confirm deadline,
handoff, phase order, overlap, grounding, and same-speaker constraints fail as intended.
