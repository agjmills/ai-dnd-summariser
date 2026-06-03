# ai-dnd-summariser

Record a Discord DnD session, transcribe it with speaker labels, get an AI-generated recap.

**macOS only.** Relies on BlackHole (virtual audio device) and AVFoundation for capture. Tested on Apple Silicon.

## One-time setup

1. Install [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole): `brew install blackhole-2ch`
2. **Audio MIDI Setup** → create a Multi-Output Device with your headphones + BlackHole 2ch ticked.
3. Set that Multi-Output as your Mac's audio output (or just Discord's output).
4. Get a HuggingFace token at huggingface.co/settings/tokens.
5. Accept terms at https://huggingface.co/pyannote/speaker-diarization-community-1.
6. Put the token in `.env`:
   ```
   HF_TOKEN=hf_...
   ```

## Use

**Record** (Ctrl-C to stop):
```
./record.sh
```

**Transcribe** (writes `.txt` + `.json` alongside the wav):
```
uv run python transcribe.py recordings/<file>.wav --model small
```
Models: `tiny`, `base`, `small` (recommended), `medium`. Bigger = slower + better. CPU-only on Apple Silicon, so a 4-hour session at `small` ≈ a few hours.

**Recap** — open Claude Code in this dir and ask it to recap the latest session. The `dnd-recap` skill handles the rest.
