#!/usr/bin/env bash
set -euo pipefail

# Record BlackHole 2ch to a timestamped wav. Ctrl-C to stop.
# 16kHz mono is what Whisper wants; we downmix on the fly.

mkdir -p recordings
OUT="recordings/$(date +%Y-%m-%d-%H%M%S).wav"

echo "Recording from BlackHole 2ch -> $OUT"
echo "Press Ctrl-C to stop."

ffmpeg -hide_banner -loglevel warning -stats \
  -f avfoundation -i ":1" \
  -ac 1 -ar 16000 -c:a pcm_s16le \
  "$OUT"
