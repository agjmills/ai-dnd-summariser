#!/usr/bin/env bash
set -uo pipefail

# Record + live-publish + auto-transcribe a DnD session, end to end.
#
#   1. Records Discord + mic to one timestamped wav (the canonical source of truth).
#   2. Live transcript: catchup.py tails the growing wav (read-only) -> <wav>.live.txt.
#   3. Live web feed: serve.py serves localhost:8000 (or the next free port up) and
#      pushes the summary to the remote /live page (https://karneia.asdfx.us/live)
#      while the session is live.
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

# Give the live stack a moment to bind/start, then make sure it actually came up.
# The recording is already safe either way — but a dead serve.py means nothing reaches
# the remote /live page, and silently discovering that after the session is no fun.
/bin/sleep 3
LOCAL_URL="http://localhost:8000"
if kill -0 "$SERVE_PID" 2>/dev/null; then
  # serve.py may have walked past a taken port — report the one it actually bound.
  PORT_LINE=$(grep -oE "http://0\.0\.0\.0:[0-9]+" /tmp/karneia-serve.log | tail -1)
  [[ -n "$PORT_LINE" ]] && LOCAL_URL="http://localhost:${PORT_LINE##*:}"
else
  echo ""
  echo "!! WARNING: serve.py died — no live web feed, and NOTHING is being pushed to"
  echo "!!          https://karneia.asdfx.us/live. Recording + transcript are unaffected."
  echo "!!          Last lines of /tmp/karneia-serve.log:"
  sed 's/^/!!            /' <(tail -5 /tmp/karneia-serve.log)
  echo "!!          Fix it, then in another shell: python3 serve.py \"$LIVE_TXT\""
  LOCAL_URL="(serve.py not running)"
fi
if ! kill -0 "$CATCHUP_PID" 2>/dev/null; then
  echo ""
  echo "!! WARNING: catchup.py died — no live transcript, so the feed will stay empty."
  echo "!!          Recording is unaffected; last lines of /tmp/karneia-catchup.log:"
  sed 's/^/!!            /' <(tail -5 /tmp/karneia-catchup.log)
fi

echo ""
echo "● Recording. Live feed:"
echo "    local:   $LOCAL_URL"
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
