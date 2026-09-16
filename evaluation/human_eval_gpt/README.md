# GPT-Live human-content validation

The frozen debate sample is in `selection_manifest.json`: 16 debates and all
156 scored triggers within them. It was selected with seed `20260916` from the
249-debate release subset. Do not replace IDs after GPT inference arrives.

YunJun's inference artifact must retain `debate_id` (`Lxxx`) and the scorer's
`probe_id` (`Lxxx_pYY`). Run the unified evaluator first, then create human
items by joining the resulting `<gpt>_scores/Lxxx.json` files to this manifest.
Each saved response must use the stable key
`gpt-live:<debate_id>:<probe_id>:c<criterion_index>`.

The human screen must show three preceding English turns, the GPT utterance,
the English criterion, and Korean fixed instructions. It must not show GT
before a response. Missing GPT utterances are recorded as a scorer-side miss;
they must not be presented as an ordinary Luna-vs-human content comparison.
