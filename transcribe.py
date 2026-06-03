"""Transcribe a wav with WhisperX. Diarization on if HF_TOKEN env var is set."""
import argparse
import os
import sys
import json
from pathlib import Path

# Load .env if present (no dependency)
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import whisperx

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", help="Path to wav/mp3 file")
    ap.add_argument("--model", default="base", help="tiny|base|small|medium|large-v3")
    ap.add_argument("--language", default="en")
    ap.add_argument("--no-diarize", action="store_true")
    args = ap.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        sys.exit(f"not found: {audio_path}")

    # Apple Silicon: WhisperX upstream is CPU-only on Mac (no CUDA, MPS not supported by faster-whisper).
    device = "cpu"
    compute_type = "int8"

    print(f"loading whisper model={args.model} on {device}", file=sys.stderr)
    model = whisperx.load_model(args.model, device, compute_type=compute_type, language=args.language)

    print("transcribing...", file=sys.stderr)
    audio = whisperx.load_audio(str(audio_path))
    result = model.transcribe(audio, batch_size=8)

    print("aligning...", file=sys.stderr)
    align_model, metadata = whisperx.load_align_model(language_code=result["language"], device=device)
    result = whisperx.align(result["segments"], align_model, metadata, audio, device, return_char_alignments=False)

    hf_token = os.environ.get("HF_TOKEN")
    if hf_token and not args.no_diarize:
        print("diarizing...", file=sys.stderr)
        diarize_model = whisperx.diarize.DiarizationPipeline(token=hf_token, device=device)
        diarize_segments = diarize_model(audio)
        result = whisperx.assign_word_speakers(diarize_segments, result)
    else:
        print("skipping diarization (set HF_TOKEN to enable)", file=sys.stderr)

    out_txt = audio_path.with_suffix(".txt")
    out_json = audio_path.with_suffix(".json")
    with out_json.open("w") as f:
        json.dump(result, f, indent=2, default=str)

    with out_txt.open("w") as f:
        for seg in result["segments"]:
            spk = seg.get("speaker", "?")
            start = seg.get("start", 0)
            text = seg.get("text", "").strip()
            line = f"[{start:7.2f}s] {spk}: {text}"
            print(line)
            f.write(line + "\n")

    print(f"\nwrote {out_txt} and {out_json}", file=sys.stderr)

if __name__ == "__main__":
    main()
