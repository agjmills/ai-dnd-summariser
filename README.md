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

## Live mode (transcript + web feed while you play)

`./live.sh` does the whole arc in one command: it records, shows a live transcript and a web feed *during* the session, and automatically runs the diarised transcription when you stop.

```
./live.sh                          # Ctrl-C to stop -> auto-transcribes
SYS=:1 MIC=:2 ./live.sh            # skip the device prompts
TRANSCRIBE_MODEL=small ./live.sh   # faster final pass (default: medium)
```

While recording it starts two helpers, both **read-only** against the wav (the recording is always the source of truth — if a helper dies, the wav is unaffected):

- **`catchup.py`** tails the growing wav and transcribes it in ~30s chunks with whisper.cpp (the fast `base` model) into `<wav>.live.txt`. Lower fidelity than the final pass and no speaker labels — just enough to follow along live.
- **`serve.py`** turns that rolling transcript into a liveblog-style feed of event posts (via the DeepSeek API) and serves it at <http://localhost:8000>. If configured, it also mirrors the feed to a remote page so others can watch.

On Ctrl-C the wav is finalised, the helpers stop, and `transcribe.py` runs the high-fidelity diarised pass automatically — then recap as usual.

### Live feed config (optional)

Add to `.env`:
```
DEEPSEEK_API_KEY=sk-...                       # required for the event summaries
LIVE_PUSH_URL=https://<host>/api/live         # optional: mirror to a remote page
LIVE_PUSH_TOKEN=<shared-secret>               # optional: auth for the push
```
Without the push vars the local feed at `localhost:8000` still works on its own. The remote side is a small Cloudflare Worker that stores the latest summary blob (freshness-gated, so the page goes dark when the session ends) and serves a `/live` page; see `serve.py` for the payload it pushes.

## How it works

See [HOW_IT_WORKS.md](HOW_IT_WORKS.md) for a walkthrough of the pipeline: BlackHole capture → Whisper (via whisper.cpp, Metal) → pyannote diarisation (MPS) → Claude recap.
