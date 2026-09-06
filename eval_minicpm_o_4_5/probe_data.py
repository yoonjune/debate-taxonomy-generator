#!/usr/bin/env python3
# khs_claude_code: reads a probe set and produces exactly what a model runner needs for one probe.
# Nothing here is model specific, so both evaluation branches carry the same file.
#
# Every path is an argument with a sensible default rather than a fixed location, so a
# later probe set with more debates, different windows or a different prompt is a flag
# and not an edit. The only structural assumptions are the field names in probes.jsonl
# and debates.jsonl.
#
# The one fact everything else rests on: make_probe_audio.py builds each probe wav as
# mix[:window_end], so sample zero of the probe wav IS second zero of the debate. The
# t_earliest, t_deadline and t_latest in probes.jsonl are on that same timeline, so a
# speaking time measured from the start of the probe wav compares to them with no
# offset. Do not trim or pad the probe audio.
"""Load a debate probe set and build one runnable item per probe."""
import json
import pathlib

PLACEHOLDERS = ("{{MOTION}}", "{{PRO_NAME}}", "{{CON_NAME}}", "{{CROSSFIRE_SEC}}")


def find_data_sample(start=None):
    """Walk up from here until a directory holding probes.jsonl is found."""
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
    """Substitute the four placeholders, as data_sample/README.md specifies.

    A template with no placeholders is returned unchanged, so a hand written prompt can
    be dropped in with --system-prompt without having to fake the fields.
    """
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
    """Every probe, with its audio, its system prompt and its moderator voice.

    All five inputs are overridable, so pointing this at a new probe set, a different
    prompt or a regenerated audio directory needs no code change.
    """

    def __init__(self, root=None, probes=None, debates=None, system_prompt=None,
                 probe_audio=None, voices=None):
        self.root = pathlib.Path(root) if root else find_data_sample()
        self.probes_path = pathlib.Path(probes or self.root / "probes.jsonl")
        self.debates_path = pathlib.Path(debates or self.root / "debates.jsonl")
        self.prompt_path = pathlib.Path(system_prompt or self.root / "system_prompt.md")
        self.audio_dir = pathlib.Path(probe_audio or self.root / "probe_audio")
        self.voices_dir = pathlib.Path(voices or self.root / "voices")
        self.debates = {d["debate_id"]: d for d in read_jsonl(self.debates_path)}
        self.probes = read_jsonl(self.probes_path)
        self.template = self.prompt_path.read_text()
        self._timelines = {}

    def describe(self):
        return {"probes": str(self.probes_path), "debates": str(self.debates_path),
                "system_prompt": str(self.prompt_path),
                "probe_audio": str(self.audio_dir), "voices": str(self.voices_dir),
                "n_probes": len(self.probes), "n_debates": len(self.debates)}

    def missing_audio(self):
        return [p["probe_id"] for p in self.probes
                if not (self.audio_dir / f'{p["probe_id"]}.wav').exists()]

    def moderator_reference(self, debate_id):
        """The clip the moderator voice was cloned from, for voice conditioning.

        Using it is a choice, not a requirement of the benchmark. The moderator already
        speaks in the probe audio with this voice, so conditioning on it keeps the model
        from answering in a voice nobody in the debate has heard. Pass use_reference
        False to the runner to drop it.
        """
        mod = self.debates[debate_id]["speakers"]["MOD"]
        wav = self.voices_dir / f'{mod["voice_id"]}.wav'
        return wav if wav.exists() else None

    def timeline(self, debate_id):
        """The per turn timeline with real start and end seconds, from audio/mix.

        debates.jsonl carries a words per minute estimate rather than measured times, so
        this is the only place to read a real clock from.
        """
        if debate_id not in self._timelines:
            self._timelines[debate_id] = json.load(
                open(self.root / "audio/mix" / f"{debate_id}.json"))
        return self._timelines[debate_id]

    def item(self, probe, use_reference=True):
        d = self.debates[probe["debate_id"]]
        return {
            "probe": probe, "root": self.root,
            "probe_id": probe["probe_id"],
            "debate_id": probe["debate_id"],
            "audio": self.audio_dir / f'{probe["probe_id"]}.wav',
            "system_prompt": build_system_prompt(self.template, d),
            "reference_wav": (self.moderator_reference(probe["debate_id"])
                              if use_reference else None),
            "voice_id": d["speakers"]["MOD"]["voice_id"],
            "label": probe["label"],
            "kind": probe["kind"],
            "t_earliest": probe["t_earliest"],
            "t_deadline": probe["t_deadline"],
            "t_latest": probe["t_latest"],
        }

    def items(self, debate_ids=None, probe_ids=None, labels=None, kinds=None,
              limit=0, use_reference=True):
        """Select probes. Every filter is optional and they compose."""
        rows = self.probes
        if debate_ids:
            rows = [p for p in rows if p["debate_id"] in set(debate_ids)]
        if probe_ids:
            rows = [p for p in rows if p["probe_id"] in set(probe_ids)]
        if labels:
            rows = [p for p in rows if p["label"] in set(labels)]
        if kinds:
            rows = [p for p in rows if p["kind"] in set(kinds)]
        if limit:
            rows = rows[:limit]
        return [self.item(p, use_reference) for p in rows]


if __name__ == "__main__":
    import collections
    ps = ProbeSet()
    d = ps.describe()
    for k, v in d.items():
        print(f"[probe_data] {k:14} {v}")
    miss = ps.missing_audio()
    print(f"[probe_data] {'probe wavs':14} "
          + (f"MISSING {len(miss)}, run make_probe_audio.py" if miss else "all present"))
    print(f"[probe_data] {'labels':14} "
          f"{dict(collections.Counter(p['label'] for p in ps.probes))}")
    print(f"[probe_data] {'kinds':14} "
          f"{dict(collections.Counter(p['kind'] for p in ps.probes))}")
