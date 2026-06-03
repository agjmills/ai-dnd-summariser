#!/usr/bin/env bash
set -euo pipefail

# Record Discord audio (via BlackHole) + your mic, mixed into one timestamped wav.
# 16kHz mono is what Whisper wants; we downmix on the fly.
#
# Skip prompts by setting env vars:
#   SYS=:1 MIC=:2 ./record.sh

mkdir -p recordings
OUT="recordings/$(date +%Y-%m-%d-%H%M%S).wav"

DEVICES=$(ffmpeg -f avfoundation -list_devices true -i "" 2>&1 || true)
DEVICES=$(echo "$DEVICES" \
  | awk '/AVFoundation audio devices:/{flag=1; next} flag && /\[[0-9]+\]/{print}')

pick_device() {
  local prompt="$1"
  local default_name="$2"
  echo "" >&2
  echo "$prompt" >&2
  echo "$DEVICES" | sed -E 's/.*indev @ [^ ]+\] //' >&2
  local default_idx
  default_idx=$(echo "$DEVICES" | grep -i "$default_name" | head -1 | sed -E 's/.*\[([0-9]+)\].*/\1/' || true)
  local prompt_suffix=""
  [[ -n "$default_idx" ]] && prompt_suffix=" [default: $default_idx]"
  local choice
  read -r -p "Enter device index${prompt_suffix}: " choice
  choice="${choice:-$default_idx}"
  if [[ -z "$choice" ]]; then
    echo "no choice and no default" >&2
    exit 1
  fi
  echo ":$choice"
}

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
