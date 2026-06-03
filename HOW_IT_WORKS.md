# How it works

A walkthrough of the pipeline this repo implements: from "audio playing in Discord" to "structured session recap."

## The pipeline at a glance

```
 ┌─────────────────┐    ┌──────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌──────────┐
 │ Discord audio   │───▶│ BlackHole +  │───▶│ ffmpeg           │───▶│ whisper.cpp     │───▶│ pyannote │
 │ + your mic      │    │ Multi-Output │    │ (mix + 16kHz)    │    │ (Whisper small) │    │ (diarise)│
 └─────────────────┘    └──────────────┘    └──────────────────┘    └─────────────────┘    └────┬─────┘
                                                                                                 │
                                                                                                 ▼
                                                                                          ┌────────────┐
                                                                                          │ merge by   │
                                                                                          │ overlap    │
                                                                                          └─────┬──────┘
                                                                                                │
                                                                                                ▼
                                                                                          ┌─────────────┐
                                                                                          │ Claude      │
                                                                                          │ (dnd-recap) │
                                                                                          └─────────────┘
```

## 1. Capture — BlackHole + Multi-Output Device

macOS has no built-in way for a process to read system audio output. To work around that we use [BlackHole](https://github.com/ExistentialAudio/BlackHole), a free virtual audio device. We then make a **Multi-Output Device** in *Audio MIDI Setup* that ticks both your real output (speakers/headphones) *and* BlackHole.

When macOS sends audio to the Multi-Output Device, it gets duplicated: one copy plays through your speakers, an identical copy flows into BlackHole. Anything that listens to BlackHole as an input device gets a perfect digital copy of whatever Discord (or anything else routed there) was playing.

Your own voice is a separate audio path — it goes into your mic, into Discord, but doesn't come back out the speakers. So `record.sh` opens **two** ffmpeg input streams: BlackHole (everyone else) + your mic (you), and mixes them into one mono 16 kHz WAV using ffmpeg's `amix` filter:

```
[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=0[mix]
```

16 kHz mono is what Whisper expects internally, so we downmix at capture time rather than later.

## 2. Transcription — Whisper via whisper.cpp

**Whisper** is OpenAI's open-weights speech recognition model. It's an encoder-decoder transformer trained on 680 000 hours of multilingual web audio. We use the **`small`** size (~244M parameters, ~466 MB on disk). Sizes range from `tiny` to `large-v3` — bigger is more accurate, especially on proper nouns and accented speech, at proportionally more compute.

Internally, Whisper:
1. Slices the audio into 30-second chunks.
2. Converts each chunk into a **log-mel spectrogram** (a 2D representation of frequency content over time).
3. Feeds the spectrogram through the **encoder**, producing a sequence of audio embeddings.
4. The **decoder** autoregressively predicts text tokens. Whisper has a special vocabulary that includes timestamp tokens, so it produces text *and* timestamps in one pass.

We don't run Whisper through PyTorch directly. We use [`whisper.cpp`](https://github.com/ggerganov/whisper.cpp), a C++ reimplementation by Georgi Gerganov built on the GGML tensor library. It supports Apple's **Metal** GPU backend, so on Apple Silicon the matrix multiplications run on the M1/M2/M3 GPU cores instead of the CPU. This is the difference between *"4-hour session takes 20 minutes"* and *"4-hour session takes 2-3 hours."*

The alternative — `faster-whisper` (which is what WhisperX uses) — runs through CTranslate2, which currently has **no Metal/MPS backend on macOS**. CTranslate2 falls back to CPU, which is the bottleneck the project's gone out of its way to avoid.

The `ggml-<size>.bin` model files come from [HuggingFace](https://huggingface.co/ggerganov/whisper.cpp) and are downloaded on first use into `models/`.

## 3. Diarisation — pyannote/speaker-diarization-community-1

Whisper gives us text and timestamps, but it has no idea **who** is speaking. For that we use [pyannote.audio](https://github.com/pyannote/pyannote-audio), and specifically the pre-trained `pyannote/speaker-diarization-community-1` pipeline.

This is a three-stage pipeline:

1. **Voice activity detection (VAD)** — a small neural model classifies each short audio window as "speech" or "non-speech." This filters out silence, music, and noise.
2. **Speaker embedding & segmentation** — speech is cut into ~1-second windows. Each window is passed through a speaker embedding model (variant of ECAPA-TDNN) that produces a fixed-length vector summarising voice characteristics: pitch, timbre, prosody — *not* what was said.
3. **Agglomerative clustering** — embeddings are clustered. Windows whose embeddings are close in vector space are grouped together as the same speaker. The number of speakers is *inferred* by the clustering algorithm, not specified up front.

The output is a sequence of "turns" — `(start_time, end_time, SPEAKER_XX)` — where `SPEAKER_XX` is an arbitrary label like `SPEAKER_00`, `SPEAKER_01`, etc. The labels are **unsupervised**: there's no notion of "the DM" or "Player 2"; the model just says *"these utterances sound like the same voice."* Mapping labels to real names is a manual step.

pyannote runs as a PyTorch model. We move it onto Apple's **MPS** (Metal Performance Shaders) backend with `.to(torch.device("mps"))`, so this stage is also GPU-accelerated.

A small wrinkle: `pyannote/speaker-diarization-community-1` is a *gated* model on HuggingFace — you have to accept its license terms once on the model page, then pass a HuggingFace token (`HF_TOKEN` in `.env`) so the library can download the weights.

## 4. Merge — assign speakers to transcript segments

`transcribe.py` now has two separate streams of information:

- **Whisper segments**: `[(start, end, text), ...]`
- **pyannote turns**: `[(start, end, speaker), ...]`

These don't perfectly align — Whisper's segment boundaries are driven by natural speech pauses, while pyannote's turn boundaries are driven by detected speaker changes. The merge logic is simple: for each Whisper segment, look at every pyannote turn, compute the temporal overlap, and assign the segment to whichever speaker has the largest overlap.

```python
for seg in segments:
    best_speaker = "?"
    best_overlap = 0.0
    for t_start, t_end, speaker in turns:
        overlap = max(0.0, min(seg["end"], t_end) - max(seg["start"], t_start))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker
    seg["speaker"] = best_speaker
```

This is the same approach WhisperX uses internally, just transparent and ~30 lines instead of a library call.

The output is the diarized transcript: lines of the form `[12.34s] SPEAKER_02: text...`, written to `<wav>.txt` and `<wav>.json`.

## 5. Recap — Claude with the dnd-recap skill

The final stage is just a language model. The diarized transcript is given to Claude (Anthropic's API, via Claude Code in this repo) along with the instructions in `.claude/skills/dnd-recap/SKILL.md`.

The skill tells Claude to:
1. Read the transcript.
2. Identify which `SPEAKER_XX` is the DM by content (narration, NPC voicing, calling for rolls).
3. Ask the user to confirm DM and player-character names — speakers are anonymous, and Claude should *not* guess character names from training data.
4. Write a structured recap covering plot beats, NPCs, decisions, loot, open hooks, and memorable moments — skipping procedural or out-of-character chatter.
5. Save to `recordings/<name>-recap.md`.

Unlike steps 1-4 which all run locally on your Mac, this step is a network call to Anthropic's API.

## Where the compute goes

| Stage | Where it runs | Rough speed |
|---|---|---|
| Audio capture (ffmpeg) | CPU, negligible | realtime (by definition) |
| Whisper transcription (whisper.cpp) | M1 Pro GPU (Metal) | ~10× realtime at `small` |
| Diarisation (pyannote) | M1 Pro GPU (MPS) | ~30-60× realtime |
| Merge | CPU, trivial | instant |
| Recap (Claude) | Anthropic API | seconds |

For a 4-hour DnD session, the whole local pipeline (transcribe + diarise) lands around 15-30 minutes on an M1 Pro.

## Knobs worth knowing

- **Model size** (`--model`): `small` is the default; bump to `medium` (~1.5 GB) if proper nouns matter and you can wait ~3× longer.
- **`--no-diarize`**: skip pyannote entirely; faster but you get one anonymous speaker for everything.
- **`HF_TOKEN`**: required to download the pyannote weights the first time.
- **`SYS` / `MIC` env vars on `record.sh`**: bypass the interactive device picker.

## Things this pipeline is NOT

- **Not realtime.** It's a record-then-transcribe workflow. Realtime diarized streaming is much harder and isn't the goal here.
- **Not multi-track.** Everything is mixed into one mono stream before transcription, so diarization has to disentangle overlapping voices in software. If diarization quality matters more than convenience, recording each speaker on a separate track (e.g. with Discord's Craig bot) skips the disentangling step entirely.
- **Not cross-session memory.** The recap skill reads one transcript at a time. It doesn't know about earlier sessions unless you paste their recaps into the conversation.
