#!/usr/bin/env python3
"""Extract existing final trigger matching without inference or new judgments."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--evaluation-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args()
source = args.evaluation_dir
out = args.output_dir
out.mkdir(parents=True, exist_ok=True)
(out / 'debates').mkdir(exist_ok=True)
final = json.loads((source / 'final_evaluation.json').read_text())
scaffold = json.loads((source / 'review_scaffold.json').read_text())
runs = {r['debate_id']: r for r in scaffold['runs']}
by_debate = defaultdict(list)
records = []
for row in final['rows']:
    candidate = row['candidate']
    record = {
        'debate_id': row['debate_id'], 'probe_id': row['probe_id'],
        'code': row['code'], 'phase': row['phase'],
        'trigger_text': row['trigger_text'],
        'response_text': candidate['text'] if candidate else None,
        'response_utterance_id': candidate['utterance_id'] if candidate else None,
        'timing': row['timing'],
        'session_window_sec': row['session_window_sec'],
        'response_session_start_sec': candidate['start_sec'] if candidate else None,
    }
    if candidate:
        turns = {t['turn']: t for t in runs[row['debate_id']]['model_turns']}
        assert candidate['text'] == turns[candidate['turn']]['text']
    records.append(record)
    by_debate[row['debate_id']].append(record)
assert set(by_debate) == set(final['selected_debates']) == set(runs)
assert len(records) == final['primary_n']
assert len({r['probe_id'] for r in records}) == len(records)
index = []
for debate_id, rows in sorted(by_debate.items()):
    lines = [f"{debate_id} — {runs[debate_id]['motion']}", '',
             '입력은 합성 토론 대본, GPT는 기존 서버 전사입니다.',
             '매칭 없음은 해당 trigger에 연결된 응답이 없다는 뜻입니다.', '']
    for row in rows:
        lines += [f"[{row['probe_id']} | {row['code']} | phase {row['phase']}]", 'TRIGGER']
        for turn in row['trigger_text']:
            lines.append(f"{turn['speaker']}: {turn['text']}")
        if not row['trigger_text']:
            lines.append('(입력 문맥 없음)')
        lines += ['GPT: ' + (row['response_text'] if row['response_text'] is not None else '(매칭된 응답 없음)'), '']
    (out / 'debates' / f'{debate_id}.txt').write_text('\n'.join(lines), encoding='utf-8')
    index.append(f"| [{debate_id}](debates/{debate_id}.txt) | {len(rows)} | {sum(r['response_text'] is not None for r in rows)} |")
(out / 'triggers.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records), encoding='utf-8')
counts = Counter(r['timing'] for r in records)
manifest = {
    'source_evaluation': source.name,
    'source_campaign': source.parent.name,
    'source_sha256': {n: hashlib.sha256((source / n).read_bytes()).hexdigest() for n in ['final_evaluation.json', 'review_scaffold.json']},
    'debate_count': len(by_debate), 'trigger_count': len(records),
    'matched_trigger_count': sum(r['response_text'] is not None for r in records),
    'timing_counts': dict(counts), 'new_inference': False, 'new_evaluation': False, 'human_gold': False,
    'excluded_debates': {'L185': 'provider content_filter; incomplete run', 'L226': 'provider content_filter; incomplete run'},
}
(out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
readme = f'''# GPT live — 토론별 trigger 텍스트

최종 선택된 **{len(by_debate)}개 토론 / {len(records):,}개 trigger**의 입력 문맥과 GPT 응답입니다.
토론별 `.txt`는 아래 링크에서 확인할 수 있습니다. 오디오와 원시 이벤트는 포함하지 않습니다.

- `TRIGGER`: 최종 평가 `rows[].trigger_text`에 저장된 participant 대본 원문입니다. 실제 입력 ASR가 아니며, trigger 시점 이후까지 이어지는 전체 발화가 포함될 수 있습니다.
- `GPT`: 최종 평가 `rows[].candidate.text`에 연결된 실제 GPT 서버 전사입니다. 원문을 수정하거나 요약하지 않았습니다.
- `(매칭된 응답 없음)`: 해당 trigger에 매칭된 응답이 없습니다. 토론 전체에서 GPT가 침묵했다는 의미는 아닙니다.
- 기존 시간 매칭을 그대로 보존했습니다. 연결된 응답이 내용상 올바르다는 뜻은 아니며, 하나의 발화가 여러 trigger에 연결될 수 있습니다.
- 시작 안내와 trigger에 연결되지 않은 추가 발화는 이 추출 범위에 포함하지 않습니다.
- L185/L226은 content_filter로 실행이 불완전하여 최종 249개에서 제외되었습니다.

`triggers.jsonl`은 같은 텍스트와 probe ID, phase, 기존 timing, session 시간, 응답 ID를 담습니다.
시간은 session clock이며 원본 토론 시간과 다릅니다. `manifest.json`에는 원본 파일 SHA-256과 추출 수를 기록했습니다.
새 inference·ASR·평가를 수행하지 않았으며, 이 파일은 human gold가 아닙니다.

## 재현

```sh
python3 export_trigger_text.py --evaluation-dir /path/to/evaluation_luna_eval_setting_249 --output-dir /path/to/export
```

## 토론 목록

| 토론 | Trigger 수 | 응답 매칭 수 |
| --- | ---: | ---: |
''' + '\n'.join(index) + '\n'
(out / 'README.md').write_text(readme, encoding='utf-8')
print(json.dumps(manifest, ensure_ascii=False, indent=2))
