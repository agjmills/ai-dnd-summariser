#!/usr/bin/env bash
set -euo pipefail

# Record Discord audio (via BlackHole) + your mic, mixed into one timestamped wav.
# 16kHz mono is what Whisper wants; we downmix on the fly.
#
# Skip prompts by setting env vars:
#   SYS=:1 MIC=:2 ./record.sh

mkdir -p recordings
OUT="recordings/$(date +%Y-%m-%d-%H%M%S).wav"

source "$(dirname "$0")/lib.sh"

SYS="${SYS:-$(pick_device "System audio (Discord output — pick BlackHole):" "BlackHole")}"
MIC="${MIC:-$(pick_device "Your mic:" "USB Audio")}"

echo ""
echo "Recording SYS=$SYS + MIC=$MIC -> $OUT"
echo "Press Ctrl-C to stop."

ffmpeg -hide_banner -loglevel warning -stats \
  -f avfoundation -i "$SYS" \
  -f avfoundation -i "$MIC" \
  -filter_complex "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=0[mix]" \
  -map "[mix]" -ac 1 -ar 16000 -c:a pcm_s16le \
  "$OUT"
