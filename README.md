# ai-dnd-summariser

Record a Discord DnD session, transcribe it with speaker labels, get an AI-generated recap.

**macOS / Apple Silicon only.** Relies on BlackHole (virtual audio device), AVFoundation for capture, and Metal/MPS for GPU-accelerated transcription.

## One-time setup

1. Install dependencies:
   ```
   brew install blackhole-2ch whisper-cpp ffmpeg
   ```
2. **Audio MIDI Setup** → create a Multi-Output Device with your headphones + BlackHole 2ch ticked.
3. Set that Multi-Output as your Mac's audio output (or just Discord's output).
4. Get a HuggingFace token at huggingface.co/settings/tokens.
5. Accept terms at https://huggingface.co/pyannote/speaker-diarization-community-1.
6. Put the token in `.env`:
   ```
   HF_TOKEN=hf_...
   ```
7. Download a whisper.cpp model (e.g. `small`):
   ```
   mkdir -p models
   curl -L -o models/ggml-small.bin \
     https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
   ```

## Use

**Record** (Ctrl-C to stop):
```
./record.sh
```

**Transcribe** with Metal GPU + diarisation (writes `.txt` + `.json` alongside the wav):
```
uv run python transcribe_metal.py recordings/<file>.wav --model small
```
Models: `tiny`, `base`, `small` (recommended), `medium`, `large-v3`. Download the matching `ggml-<model>.bin` into `models/` first. A 4-hour session at `small` takes roughly 15-30 min on an M1 Pro.

**Recap** — open Claude Code in this dir and ask it to recap the latest session. The `dnd-recap` skill handles the rest.

## Fallback: CPU-only path

If whisper.cpp / Metal isn't available, `transcribe.py` runs the same job through WhisperX on CPU. Much slower (a 4-hour session ≈ 2-3 hours), no extra setup beyond `uv sync`.
