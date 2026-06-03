---
name: dnd-recap
description: Summarise a diarized DnD session transcript (output of transcribe.py) into a session recap. Use when the user asks to summarise, recap, or write up a DnD session, or points to a transcript file in recordings/.
---

# DnD session recap

You are recapping a Dungeons & Dragons session from a diarized transcript produced by `transcribe.py` in this repo. The transcript format is:

```
[   0.29s] SPEAKER_00: ...
[   3.14s] SPEAKER_01: ...
```

Speakers are anonymous (`SPEAKER_00`, `SPEAKER_01`, ...) because diarization is unsupervised. One of them is the DM; the rest are players.

## Steps

1. **Read the transcript.** If the user didn't name one, look in `recordings/` and pick the most recent `.txt`. If there's no `.txt` but there's a `.wav`, tell the user they need to run `transcribe.py` first.
2. **Identify speakers.** Read enough of the transcript to guess which `SPEAKER_XX` is the DM (talks more, narrates scenes, voices NPCs, calls for rolls). Ask the user to confirm DM + player character names before writing the recap — don't guess character names from training data.
3. **Write the recap** with these sections, omitting any that have no content:
   - **Where we left off** (1 sentence)
   - **What happened** (chronological bullet points — plot beats, not blow-by-blow)
   - **NPCs met** (name, role, vibe, current disposition toward party)
   - **Decisions made** (party choices that will matter later)
   - **Loot & rewards**
   - **Open threads / hooks** (unresolved questions, foreshadowing, things the DM dropped that the party hasn't picked up on)
   - **Memorable moments** (jokes, crits, character moments — short)
4. **Length.** Aim for something a player can read in 2 minutes before next session. Cut anything that's just procedural ("we rolled initiative", "took a short rest") unless it mattered.

## What to avoid

- Don't invent details. Transcription is imperfect — names of spells, NPCs, and places will often be garbled. When unsure, write `[unclear: "best guess"]` rather than guess silently.
- Don't quote SPEAKER_XX labels in the final recap — translate to character/player names once confirmed.
- Don't summarise out-of-character chatter (snack runs, rules debates, real-world tangents) unless explicitly funny enough to include under "memorable moments".
- Don't editorialise — the recap is for the table, not a review of the session.

## Output

Write to `recordings/<same-basename>-recap.md` and also print to stdout. If a recap already exists, ask before overwriting.
