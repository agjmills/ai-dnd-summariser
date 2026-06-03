"""Fast transcription using whisper.cpp (Metal GPU) + pyannote (MPS) diarisation.

Same input/output contract as transcribe.py: takes a wav, writes <name>.txt + <name>.json.
Runs ~10-15x faster than transcribe.py on Apple Silicon.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import wave
import numpy as np
import torch
from pyannote.audio import Pipeline


def load_wav(path: Path) -> tuple[torch.Tensor, int]:
    """Load wav with Python's stdlib, return (waveform, sample_rate). Avoids torchaudio backend mess."""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(n)
    if sw != 2:
        raise RuntimeError(f"expected 16-bit pcm, got sampwidth={sw}")
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    return torch.from_numpy(audio).unsqueeze(0), sr


def run_whisper_cpp(audio: Path, model: Path, language: str) -> list[dict]:
    """Returns list of {start, end, text} with times in seconds."""
    with tempfile.TemporaryDirectory() as td:
        out_base = Path(td) / "out"
        subprocess.run(
            [
                "whisper-cli",
                "-m", str(model),
                "-f", str(audio),
                "-l", language,
                "-oj",
                "-of", str(out_base),
                "-np",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        data = json.loads((out_base.with_suffix(".json")).read_text())

    segments = []
    for s in data["transcription"]:
        segments.append({
            "start": s["offsets"]["from"] / 1000.0,
            "end": s["offsets"]["to"] / 1000.0,
            "text": s["text"].strip(),
        })
    return segments


def diarize(audio: Path, hf_token: str, device: str) -> list[tuple[float, float, str]]:
    """Returns list of (start, end, speaker_label)."""
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1",
        token=hf_token,
    )
    pipeline.to(torch.device(device))
    waveform, sample_rate = load_wav(audio)
    output = pipeline({"waveform": waveform, "sample_rate": sample_rate})
    annotation = getattr(output, "speaker_diarization", output)
    return [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]


def assign_speakers(segments: list[dict], turns: list[tuple[float, float, str]]) -> list[dict]:
    """For each segment, pick the speaker whose turn overlaps most."""
    for seg in segments:
        best_speaker = "?"
        best_overlap = 0.0
        for t_start, t_end, speaker in turns:
            overlap = max(0.0, min(seg["end"], t_end) - max(seg["start"], t_start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker
        seg["speaker"] = best_speaker
    return segments


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", help="Path to wav file")
    ap.add_argument("--model", default="small", help="tiny|base|small|medium|large-v3")
    ap.add_argument("--language", default="en")
    ap.add_argument("--no-diarize", action="store_true")
    args = ap.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        sys.exit(f"not found: {audio_path}")

    model_path = Path(__file__).parent / "models" / f"ggml-{args.model}.bin"
    if not model_path.exists():
        sys.exit(
            f"missing model: {model_path}\n"
            f"download with: curl -L -o {model_path} "
            f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{args.model}.bin"
        )

    print(f"transcribing with whisper.cpp ({args.model}, Metal)...", file=sys.stderr)
    segments = run_whisper_cpp(audio_path, model_path, args.language)

    hf_token = os.environ.get("HF_TOKEN")
    if hf_token and not args.no_diarize:
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        print(f"diarising with pyannote ({device})...", file=sys.stderr)
        turns = diarize(audio_path, hf_token, device)
        segments = assign_speakers(segments, turns)
    else:
        print("skipping diarisation (set HF_TOKEN to enable)", file=sys.stderr)

    out_txt = audio_path.with_suffix(".txt")
    out_json = audio_path.with_suffix(".json")
    out_json.write_text(json.dumps(segments, indent=2))

    with out_txt.open("w") as f:
        for seg in segments:
            spk = seg.get("speaker", "?")
            line = f"[{seg['start']:7.2f}s] {spk}: {seg['text']}"
            print(line)
            f.write(line + "\n")

    print(f"\nwrote {out_txt} and {out_json}", file=sys.stderr)


if __name__ == "__main__":
    main()
