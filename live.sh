#!/usr/bin/env bash
set -uo pipefail

# Record + live-publish + auto-transcribe a DnD session, end to end.
#
#   1. Records Discord + mic to one timestamped wav (the canonical source of truth).
#   2. Live transcript: catchup.py tails the growing wav (read-only) -> <wav>.live.txt.
#   3. Live web feed: serve.py serves localhost:8000 and pushes the summary to the
#      remote /live page (https://karneia.asdfx.us/live) while the session is live.
#   4. On Ctrl-C: stops the live stack, finalises the wav, then automatically runs the
#      high-fidelity diarised transcription (transcribe.py).
#
# Everything live is READ-ONLY against the recording; if any of it dies, the wav is fine.
#
# Skip device prompts:   SYS=:1 MIC=:2 ./live.sh
# Transcription model:   TRANSCRIBE_MODEL=small ./live.sh   (default: transcribe.py's own)

cd "$(dirname "$0")"
mkdir -p recordings
OUT="recordings/$(date +%Y-%m-%d-%H%M%S).wav"
LIVE_TXT="${OUT%.wav}.live.txt"

source "./lib.sh"
SYS="${SYS:-$(pick_device "System audio (Discord output — pick BlackHole):" "BlackHole")}"
MIC="${MIC:-$(pick_device "Your mic:" "USB Audio")}"

echo ""
echo "Recording SYS=$SYS + MIC=$MIC -> $OUT"

# 1. Recording — single ffmpeg writing the canonical wav.
ffmpeg -hide_banner -loglevel warning -stats \
  -f avfoundation -i "$SYS" \
  -f avfoundation -i "$MIC" \
  -filter_complex "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=0[mix]" \
  -map "[mix]" -ac 1 -ar 16000 -c:a pcm_s16le \
  "$OUT" &
FFMPEG_PID=$!

# 2 + 3. Live transcript and web feed (stdlib only -> plain python3).
python3 catchup.py "$OUT" >/tmp/karneia-catchup.log 2>&1 &
CATCHUP_PID=$!
python3 serve.py "$LIVE_TXT" >/tmp/karneia-serve.log 2>&1 &
SERVE_PID=$!

echo ""
echo "● Recording. Live feed:"
echo "    local:   http://localhost:8000"
echo "    public:  https://karneia.asdfx.us/live   (visible while live)"
echo "    tail:    tail -f \"$LIVE_TXT\""
echo "    logs:    /tmp/karneia-catchup.log  /tmp/karneia-serve.log"
echo ""
echo "Press Ctrl-C to stop — diarised transcription runs automatically after."

stop() {
  trap '' INT TERM   # ignore further Ctrl-C while winding down / transcribing
  echo ""
  echo "Stopping recording…"
  kill -INT "$FFMPEG_PID" 2>/dev/null   # let ffmpeg finalise the wav header
  wait "$FFMPEG_PID" 2>/dev/null
  # SIGTERM so serve.py's shutdown hook fires (pushes /live offline immediately).
  kill "$CATCHUP_PID" "$SERVE_PID" 2>/dev/null
  wait "$CATCHUP_PID" "$SERVE_PID" 2>/dev/null

  echo ""
  echo "Transcribing + diarising $OUT (this takes a while)…"
  if [[ -n "${TRANSCRIBE_MODEL:-}" ]]; then
    uv run python transcribe.py "$OUT" --model "$TRANSCRIBE_MODEL"
  else
    uv run python transcribe.py "$OUT"
  fi
  echo ""
  echo "Done."
  echo "  transcript: ${OUT%.wav}.txt"
  echo "  recap next: run the dnd-recap skill on ${OUT%.wav}.txt"
  exit 0
}
trap stop INT TERM

# Block until the recording ends (Ctrl-C fires the trap; natural exit falls through).
wait "$FFMPEG_PID"
stop
