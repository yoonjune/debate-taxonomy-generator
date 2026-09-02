from __future__ import annotations

import json
import platform
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from .base import GenerationResult


class PersonaPlexAdapter:
    """Shared native runtime for base PersonaPlex and RL-Seamless.

    The checkpoint is selected only by `model_id` and `revision`. Participant
    audio is always supplied to the user codec. Ground-truth moderator audio is
    supplied to the agent codec only before `teacher_forcing_until_sec`.

    Version 0.1 forces agent acoustic tokens. The parallel text stream remains
    model-generated and is recorded. This limitation is explicit in every run
    manifest; it must not be described as exact audio+text state replay.
    """

    def __init__(self) -> None:
        self._loaded_key: tuple[str, str, str, bool] | None = None
        self._runtime: dict[str, Any] | None = None

    def generate(
        self,
        manifest: dict[str, Any],
        model_config: dict[str, Any],
        output_dir: Path,
    ) -> GenerationResult:
        started = time.monotonic()
        device = model_config.get("device", "cuda")
        model_id = model_config["model_id"]
        revision = model_config.get("revision")
        if not revision:
            raise ValueError("model revision must be pinned")
        seed = int(model_config["seed"])

        runtime = self._load_runtime(model_config)
        torch = runtime["torch"]
        _seed_all(torch, seed)

        cpu_offload = bool(model_config.get("cpu_offload", False))
        user_mimi = runtime["user_mimi"]
        teacher_mimi = runtime["teacher_mimi"]
        decoder_mimi = runtime["decoder_mimi"]
        lm_gen = runtime["lm_gen"]
        tokenizer = runtime["tokenizer"]
        frame_size = runtime["frame_size"]

        system_prompt = Path(manifest["input"]["system_prompt"]).read_text(encoding="utf-8").strip()
        voice_prompt = manifest["input"]["moderator_reference_voice"]
        lm_gen.load_voice_prompt(voice_prompt)
        lm_gen.text_prompt_tokens = tokenizer.encode(runtime["wrap_with_system_tags"](system_prompt))

        user_mimi.reset_streaming()
        teacher_mimi.reset_streaming()
        decoder_mimi.reset_streaming()
        lm_gen.reset_streaming()
        lm_gen.step_system_prompts(user_mimi)
        user_mimi.reset_streaming()

        user, user_rate = sf.read(manifest["input"]["user_audio"], dtype="float32", always_2d=True)
        teacher, teacher_rate = sf.read(
            manifest["input"]["agent_teacher_audio"], dtype="float32", always_2d=True
        )
        user = user.mean(axis=1)
        teacher = teacher.mean(axis=1)
        expected_rate = int(model_config["sample_rate"])
        if user_rate != teacher_rate or user_rate != expected_rate or user_rate != user_mimi.sample_rate:
            raise ValueError(
                f"audio rates user={user_rate}, teacher={teacher_rate}, config={expected_rate}, "
                f"model={user_mimi.sample_rate}"
            )
        if len(user) != len(teacher):
            raise ValueError("user and agent-teacher streams must have equal length")

        release_sec = float(manifest["input"]["teacher_forcing_until_sec"])
        release_frame = int(np.floor(release_sec * user_mimi.frame_rate))
        output_frames: list[np.ndarray] = []
        text_rows: list[dict[str, Any]] = []
        total_frames = int(np.ceil(len(user) / frame_size))

        for frame_index in range(total_frames):
            start = frame_index * frame_size
            end = min(len(user), start + frame_size)
            user_chunk = _audio_tensor(torch, user[start:end], frame_size, device)
            teacher_chunk = _audio_tensor(torch, teacher[start:end], frame_size, device)
            user_codes = user_mimi.encode(user_chunk)
            teacher_codes = teacher_mimi.encode(teacher_chunk)
            if user_codes.shape[-1] != teacher_codes.shape[-1]:
                raise RuntimeError("user and teacher codecs produced different frame counts")
            for code_index in range(user_codes.shape[-1]):
                force_agent = frame_index < release_frame
                tokens = lm_gen.step(
                    user_codes[:, :, code_index : code_index + 1],
                    moshi_tokens=(
                        teacher_codes[:, :, code_index : code_index + 1] if force_agent else None
                    ),
                )
                if tokens is None:
                    continue
                pcm = decoder_mimi.decode(tokens[:, 1:9]).detach().cpu().numpy()[0, 0]
                output_frames.append(pcm.astype(np.float32, copy=False))
                token_id = int(tokens[0, 0, 0].item())
                piece = None
                if token_id not in (0, 3):
                    piece = tokenizer.id_to_piece(token_id).replace("▁", " ")
                text_rows.append({
                    "time_sec": round(frame_index / user_mimi.frame_rate, 6),
                    "token_id": token_id,
                    "piece": piece,
                    "agent_audio_forced": force_agent,
                })

        output = np.concatenate(output_frames) if output_frames else np.zeros(len(user), dtype=np.float32)
        output = _fit_length(output, len(user))
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / "output.wav"
        text_path = output_dir / "output_text.json"
        sf.write(audio_path, output, user_rate, subtype="PCM_16")
        text_path.write_text(json.dumps(text_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        runtime_metadata = {
            "adapter": "personaplex",
            "model_id": model_id,
            "revision": revision,
            "device": device,
            "cpu_offload": cpu_offload,
            "seed": seed,
            "teacher_forcing": "agent_audio_only",
            "release_sec_requested": release_sec,
            "release_frame": release_frame,
            "release_sec_effective": release_frame / user_mimi.frame_rate,
            "frame_rate_hz": user_mimi.frame_rate,
            "frame_size_samples": frame_size,
            "torch_version": torch.__version__,
            "python": platform.python_version(),
            "cuda_device": torch.cuda.get_device_name(device) if device.startswith("cuda") else None,
        }
        return GenerationResult(
            output_audio=audio_path,
            output_text=text_path,
            sample_rate=user_rate,
            duration_sec=len(output) / user_rate,
            wall_time_sec=time.monotonic() - started,
            runtime_metadata=runtime_metadata,
        )

    def _load_runtime(self, model_config: dict[str, Any]) -> dict[str, Any]:
        device = model_config.get("device", "cuda")
        model_id = model_config["model_id"]
        revision = model_config["revision"]
        cpu_offload = bool(model_config.get("cpu_offload", False))
        key = (model_id, revision, device, cpu_offload)
        if self._runtime is not None:
            if key != self._loaded_key:
                raise RuntimeError("one PersonaPlexAdapter instance cannot switch checkpoints")
            return self._runtime

        torch, sentencepiece, _sphn, hf_hub_download, loaders, LMGen, helpers = _lazy_runtime_imports()
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("PersonaPlex baseline requires CUDA; no CUDA device is available")
        model_paths = {
            "mimi": hf_hub_download(model_id, loaders.MIMI_NAME, revision=revision),
            "moshi": hf_hub_download(model_id, loaders.MOSHI_NAME, revision=revision),
            "tokenizer": hf_hub_download(model_id, loaders.TEXT_TOKENIZER_NAME, revision=revision),
        }
        tokenizer = sentencepiece.SentencePieceProcessor(model_paths["tokenizer"])
        user_mimi = loaders.get_mimi(model_paths["mimi"], device)
        teacher_mimi = loaders.get_mimi(model_paths["mimi"], device)
        decoder_mimi = loaders.get_mimi(model_paths["mimi"], device)
        lm = loaders.get_moshi_lm(model_paths["moshi"], device=device, cpu_offload=cpu_offload)
        lm.eval()
        frame_size = int(user_mimi.sample_rate / user_mimi.frame_rate)
        lm_gen = LMGen(
            lm,
            device=device,
            sample_rate=user_mimi.sample_rate,
            frame_rate=user_mimi.frame_rate,
            audio_silence_frame_cnt=int(0.5 * user_mimi.frame_rate),
            use_sampling=not bool(model_config.get("greedy", False)),
            temp=float(model_config["audio_temperature"]),
            temp_text=float(model_config["text_temperature"]),
            top_k=int(model_config["audio_top_k"]),
            top_k_text=int(model_config["text_top_k"]),
        )
        user_mimi.streaming_forever(1)
        teacher_mimi.streaming_forever(1)
        decoder_mimi.streaming_forever(1)
        lm_gen.streaming_forever(1)
        self._loaded_key = key
        self._runtime = {
            "torch": torch,
            "tokenizer": tokenizer,
            "user_mimi": user_mimi,
            "teacher_mimi": teacher_mimi,
            "decoder_mimi": decoder_mimi,
            "lm_gen": lm_gen,
            "frame_size": frame_size,
            "wrap_with_system_tags": helpers["wrap_with_system_tags"],
        }
        return self._runtime


def _lazy_runtime_imports():
    try:
        import sentencepiece
        import sphn
        import torch
        from huggingface_hub import hf_hub_download
        from moshi.models import LMGen, loaders
        from moshi.offline import wrap_with_system_tags
    except ImportError as exc:
        raise RuntimeError(
            "PersonaPlex runtime is not installed. Follow baselines/MODEL_RUNTIME.md."
        ) from exc
    return torch, sentencepiece, sphn, hf_hub_download, loaders, LMGen, {
        "wrap_with_system_tags": wrap_with_system_tags,
    }


def _seed_all(torch, seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = False
    torch.backends.cudnn.benchmark = False


def _audio_tensor(torch, samples: np.ndarray, frame_size: int, device: str):
    padded = np.zeros(frame_size, dtype=np.float32)
    padded[: len(samples)] = samples
    return torch.from_numpy(padded).to(device=device).reshape(1, 1, frame_size)


def _fit_length(output: np.ndarray, target: int) -> np.ndarray:
    if len(output) >= target:
        return output[:target]
    return np.pad(output, (0, target - len(output)))
