#!/usr/bin/env python3
"""Read-only live catch-up for an in-progress recording.

Backfills everything recorded so far in one whisper pass, then tails the growing
wav and transcribes each new ~30s slice. ONLY ever reads the wav — never writes to
it, never signals ffmpeg, leaves the canonical recording + offline pipeline untouched.

Usage: python3 catchup.py [path-to-wav]   (defaults to newest in recordings/)
"""
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).parent
MODEL = ROOT / "models" / "ggml-base.bin"   # base = snappy; swap to small/medium for accuracy
CHUNK_SEC, SR, BPS = 30, 16000, 16000 * 2   # mono 16-bit => 32000 bytes/sec

if len(sys.argv) > 1:
    src = Path(sys.argv[1])
else:
    src = max((ROOT / "recordings").glob("*.wav"), key=lambda p: p.stat().st_mtime)


def data_offset(p):
    """Find byte offset of the PCM payload (don't assume a 44-byte header)."""
    with open(p, "rb") as f:
        if f.read(12)[:4] != b"RIFF":
            return None
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                return None
            cid, size = hdr[:4], struct.unpack("<I", hdr[4:8])[0]
            if cid == b"data":
                return f.tell()
            f.seek(size, 1)


def transcribe(pcm: bytes) -> str:
    """Wrap raw PCM in a temp wav and run whisper-cli; return its text lines."""
    with tempfile.NamedTemporaryFile(suffix=".wav") as tf:
        with wave.open(tf.name, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm)
        r = subprocess.run(
            ["whisper-cli", "-m", str(MODEL), "-f", tf.name,
             "-l", "en", "-nt", "-mc", "0", "-sns"],
            capture_output=True, text=True,
        )
    return r.stdout.strip()


def emit(text: str, log):
    for line in text.splitlines():
        line = line.strip()
        if line:
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()


off = None
while off is None:
    off = data_offset(src)
    if off is None:
        time.sleep(0.5)

out = src.with_suffix(".live.txt")
print(f"catching up on {src.name} -> {out.name} (model={MODEL.name})", file=sys.stderr)

backfill_sec = (src.stat().st_size - off) / BPS
print(f"streaming from start; {backfill_sec / 60:.1f} min already recorded to backfill",
      file=sys.stderr)

with out.open("a") as log:
    # Stream chunk-by-chunk from the very start of the recording. While there's a
    # backlog we run flat-out (no sleep) so backfill streams as fast as whisper goes;
    # once we reach the live edge we announce it and tail new audio as it lands.
    pos = off
    caught_up = False
    while True:
        if src.stat().st_size - pos < BPS * CHUNK_SEC:
            if not caught_up:
                caught_up = True
                emit("--- caught up; now live ---", log)
                print("--- backfill done, tailing live ---", file=sys.stderr)
            time.sleep(2)
            continue
        with open(src, "rb") as f:
            f.seek(pos)
            pcm = f.read(BPS * CHUNK_SEC)
        pos += len(pcm)
        emit(transcribe(pcm), log)
