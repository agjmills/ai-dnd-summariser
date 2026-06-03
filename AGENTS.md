# Agent instructions

Read by opencode, Aider, Cursor and any other tool that follows the AGENTS.md convention. Claude Code uses a separate skill (`.claude/skills/dnd-recap/`) that points at the same prompt.

## What this repo does

Captures Discord audio, transcribes it with whisper.cpp + pyannote diarisation, and produces a DnD session recap. See `README.md` for usage and `HOW_IT_WORKS.md` for the pipeline.

## Tasks

### Recap a session

When the user asks to summarise, recap, or write up a session — or points at a transcript file in `recordings/` — follow the instructions in [`prompts/dnd-recap.md`](prompts/dnd-recap.md).

## Conventions

- Recordings live in `recordings/` (gitignored).
- Recap output goes to `recordings/<basename>-recap.md`.
- Models for whisper.cpp live in `models/` (gitignored) and are auto-downloaded by `transcribe.py`.
- The HuggingFace token for pyannote lives in `.env` (gitignored) as `HF_TOKEN=hf_...`.
