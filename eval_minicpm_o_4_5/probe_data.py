#!/usr/bin/env python3
# KHS: reads data_sample and produces exactly what a model runner needs for one probe.
# Nothing here is model specific, so both evaluation branches carry the same file and a
# change to the data format is a change in one place per branch.
#
# The one fact that everything else rests on: make_probe_audio.py builds each probe wav
# as mix[:window_end], so sample zero of the probe wav IS second zero of the debate.
# The t_earliest, t_deadline and t_latest in probes.jsonl are on that same timeline, so
# a speaking time measured from the start of the probe wav is directly comparable to
# them with no offset. Do not trim or pad the probe audio.
"""Load the debate probe set and build one runnable item per probe."""
import json
import pathlib

PLACEHOLDERS = ("{{MOTION}}", "{{PRO_NAME}}", "{{CON_NAME}}", "{{CROSSFIRE_SEC}}")


def find_data_sample(start=None):
    """Walk up from here until a directory holding data_sample is found."""
    p = pathlib.Path(start or __file__).resolve()
    for d in [p] + list(p.parents):
        cand = d / "data_sample"
        if (cand / "probes.jsonl").exists():
            return cand
    raise FileNotFoundError("data_sample with probes.jsonl not found above " + str(p))


def read_jsonl(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_system_prompt(template, debate):
    """Substitute the four placeholders, exactly as data_sample/README.md specifies."""
    values = {
        "{{MOTION}}": debate["motion"].rstrip("."),
        "{{PRO_NAME}}": debate["speakers"]["PRO"]["name"],
        "{{CON_NAME}}": debate["speakers"]["CON"]["name"],
        "{{CROSSFIRE_SEC}}": str(debate["crossfire_end_sec"]),
    }
    out = template
    for k, v in values.items():
        out = out.replace(k, v)
    left = [k for k in PLACEHOLDERS if k in out]
    if left:
        raise ValueError("unsubstituted placeholders: " + ", ".join(left))
    return out


class ProbeSet:
    """Every probe, with its audio, its system prompt and its moderator voice."""

    def __init__(self, data_sample=None, probe_audio_dir=None):
        self.root = pathlib.Path(data_sample) if data_sample else find_data_sample()
        self.audio_dir = pathlib.Path(probe_audio_dir or self.root / "probe_audio")
        self.debates = {d["debate_id"]: d for d in read_jsonl(self.root / "debates.jsonl")}
        self.probes = read_jsonl(self.root / "probes.jsonl")
        self.template = (self.root / "system_prompt.md").read_text()

    def missing_audio(self):
        return [p["probe_id"] for p in self.probes
                if not (self.audio_dir / f'{p["probe_id"]}.wav').exists()]

    def moderator_reference(self, debate_id):
        """The wav that the moderator voice was cloned from, for voice conditioning.

        Using it is a deliberate choice, not a requirement of the benchmark. The
        moderator already speaks in the probe audio with this voice, so conditioning on
        it keeps the model from answering in a fourth voice that no listener in the
        debate has heard, which would make the output easy to tell apart for the wrong
        reason. voices.json also carries ref_text for the clip.
        """
        mod = self.debates[debate_id]["speakers"]["MOD"]
        wav = self.root / "voices" / f'{mod["voice_id"]}.wav'
        return wav if wav.exists() else None

    def item(self, probe):
        d = self.debates[probe["debate_id"]]
        return {
            "probe_id": probe["probe_id"],
            "debate_id": probe["debate_id"],
            "audio": self.audio_dir / f'{probe["probe_id"]}.wav',
            "system_prompt": build_system_prompt(self.template, d),
            "reference_wav": self.moderator_reference(probe["debate_id"]),
            "label": probe["label"],
            "kind": probe["kind"],
            "t_earliest": probe["t_earliest"],
            "t_deadline": probe["t_deadline"],
            "t_latest": probe["t_latest"],
        }

    def items(self, debate_ids=None, limit=0):
        rows = self.probes
        if debate_ids:
            keep = set(debate_ids)
            rows = [p for p in rows if p["debate_id"] in keep]
        if limit:
            rows = rows[:limit]
        return [self.item(p) for p in rows]


if __name__ == "__main__":
    ps = ProbeSet()
    miss = ps.missing_audio()
    print(f"[probe_data] data_sample  {ps.root}")
    print(f"[probe_data] debates      {len(ps.debates)}")
    print(f"[probe_data] probes       {len(ps.probes)}"
          f"  (speak {sum(1 for p in ps.probes if p['label'] != 'none')},"
          f" silent {sum(1 for p in ps.probes if p['label'] == 'none')})")
    print(f"[probe_data] probe audio  {ps.audio_dir}"
          + (f"  MISSING {len(miss)}, run data_sample/make_probe_audio.py" if miss
             else "  all present"))
    one = ps.items(limit=1)[0]
    print(f"[probe_data] example      {one['probe_id']} label={one['label']} "
          f"kind={one['kind']} window=({one['t_earliest']}, {one['t_latest']})")
    print(f"[probe_data] reference    {one['reference_wav']}")
    print(f"[probe_data] prompt head  {one['system_prompt'][:90]}...")
