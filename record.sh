#!/usr/bin/env bash
set -euo pipefail

# Record Discord audio (via BlackHole) + your mic, mixed into one timestamped wav.
# 16kHz mono is what Whisper wants; we downmix on the fly.
#
# Override device indices if needed:
#   SYS=:1   (BlackHole 2ch — Discord output)
#   MIC=:0   (your mic — defaults to AirPods)
# Run `ffmpeg -f avfoundation -list_devices true -i ""` to see indices.

mkdir -p recordings
OUT="recordings/$(date +%Y-%m-%d-%H%M%S).wav"
SYS="${SYS:-:1}"
MIC="${MIC:-:0}"

echo "Recording SYS=$SYS + MIC=$MIC -> $OUT"
echo "Press Ctrl-C to stop."

ffmpeg -hide_banner -loglevel warning -stats \
  -f avfoundation -i "$SYS" \
  -f avfoundation -i "$MIC" \
  -filter_complex "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=0[mix]" \
  -map "[mix]" -ac 1 -ar 16000 -c:a pcm_s16le \
  "$OUT"
