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

## Use

**Record** Discord output + your mic, mixed (Ctrl-C to stop):
```
./record.sh
```
By default this captures BlackHole (index `:1`) as the system audio and a USB Audio Device (`:2`) as the mic. Override with env vars if your devices differ:
```
SYS=:1 MIC=:4 ./record.sh    # MacBook Pro built-in mic instead
```
List your device indices with `ffmpeg -f avfoundation -list_devices true -i ""`.

**Transcribe** with Metal GPU + diarisation (writes `.txt` + `.json` alongside the wav):
```
uv run python transcribe.py recordings/<file>.wav --model small
```
Models: `tiny`, `base`, `small` (recommended), `medium`, `large-v3`. The matching `ggml-<model>.bin` is downloaded on first use into `models/`. A 4-hour session at `small` takes roughly 15-30 min on an M1 Pro.

**Recap** — open Claude Code in this dir and ask it to recap the latest session. The `dnd-recap` skill handles the rest.

## How it works

See [HOW_IT_WORKS.md](HOW_IT_WORKS.md) for a walkthrough of the pipeline: BlackHole capture → Whisper (via whisper.cpp, Metal) → pyannote diarisation (MPS) → Claude recap.
