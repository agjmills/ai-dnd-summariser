#!/usr/bin/env python3
"""Live session liveblog: turns the rolling transcript into an append-only feed of
event posts (newest-first), and mirrors the feed to a Cloudflare Worker.

Decoupled from catchup.py — it only READS the .live.txt that catchup.py appends to, so
transcription keeps running untouched. The raw transcript stays local; only the event
posts (summaries) are pushed to the remote /live page.

Usage: python3 serve.py [path-to-.live.txt]   (defaults to newest in recordings/)
       open http://<this-machine>:8000

Needs DEEPSEEK_API_KEY in .env for posts. Set LIVE_PUSH_URL + LIVE_PUSH_TOKEN to mirror
the feed to the remote Worker.
"""
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
PORT = int(os.environ.get("PORT", "8000"))
CYCLE = 20                    # seconds between push/extract cycles
EXTRACT_MIN_NEW = 700         # only ask for new posts once this many new chars accrued
RECENT_HEADLINES = 6          # how many prior headlines to show the model (dedup context)
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-flash"

# --- .env loader (same pattern as transcribe.py) ---
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

if len(sys.argv) > 1:
    LIVE_TXT = Path(sys.argv[1])
else:
    LIVE_TXT = max((ROOT / "recordings").glob("*.live.txt"), key=lambda p: p.stat().st_mtime)

PROMPT = (ROOT / "prompts" / "live-events.md").read_text()

# events: chronological (oldest first). Each: {seq, at|None, headline, body, backfill}
STATE = {"events": [], "updated_at": 0, "error": ""}
LOCK = threading.Lock()

LIVE_PUSH_URL = os.environ.get("LIVE_PUSH_URL", "").strip()
LIVE_PUSH_TOKEN = os.environ.get("LIVE_PUSH_TOKEN", "").strip()


def read_transcript() -> str:
    try:
        return LIVE_TXT.read_text()
    except FileNotFoundError:
        return ""


def extract_events(text: str, recent_headlines: list, backfill: bool) -> list:
    """Ask DeepSeek for new event posts from `text`. Returns [{headline, body}, ...]."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("no DEEPSEEK_API_KEY")

    if backfill:
        instruction = (
            "This is the session transcript so far. Produce the full chronological feed "
            "of event posts covering it, oldest first."
        )
    else:
        already = "\n".join(f"- {h}" for h in recent_headlines) or "(none yet)"
        instruction = (
            "Here is the NEW transcript since the last update. Already-posted headlines "
            f"(do not repeat these):\n{already}\n\nReport only genuinely new developments."
        )

    body = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": f"{instruction}\n\nTranscript:\n\n{text}"},
        ],
        "temperature": 0.3,
        "stream": False,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        DEEPSEEK_URL, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read())
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    events = parsed.get("events", []) if isinstance(parsed, dict) else []
    # keep only well-formed posts
    return [
        {"headline": str(e["headline"]).strip(), "body": str(e.get("body", "")).strip()}
        for e in events
        if isinstance(e, dict) and e.get("headline")
    ]


def push_remote(live: bool):
    """Mirror the event feed (or an 'offline' marker) to the remote Worker."""
    if not (LIVE_PUSH_URL and LIVE_PUSH_TOKEN):
        return
    with LOCK:
        payload = {
            "live": live,
            "events": STATE["events"],
            "updated_at": int(time.time()),
        }
    if live and not payload["events"]:
        return  # nothing worth showing yet
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        LIVE_PUSH_URL, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {LIVE_PUSH_TOKEN}",
            "Content-Type": "application/json",
            # Cloudflare bot protection 403s the default "Python-urllib/x.y" UA.
            "User-Agent": "karneia-live-pusher/1.0",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:  # noqa: BLE001 — best-effort mirror, don't crash the server
        print(f"remote push failed: {e}", file=sys.stderr)


def add_events(new: list, backfill: bool):
    with LOCK:
        seq = STATE["events"][-1]["seq"] + 1 if STATE["events"] else 0
        for e in new:
            STATE["events"].append({
                "seq": seq,
                "at": None if backfill else int(time.time()),
                "headline": e["headline"],
                "body": e["body"],
                "backfill": backfill,
            })
            seq += 1
        STATE["updated_at"] = int(time.time())


def feed_loop():
    cursor = 0
    # --- backfill: turn the session so far into the initial feed ---
    full = read_transcript()
    if full.strip():
        try:
            evs = extract_events(full, [], backfill=True)
            add_events(evs, backfill=True)
            print(f"backfilled {len(evs)} posts from session so far", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            with LOCK:
                STATE["error"] = f"backfill: {e}"
            print(f"backfill failed: {e}", file=sys.stderr)
        cursor = len(full)
    push_remote(live=True)

    # --- live: extract new posts from new transcript as it arrives ---
    while True:
        time.sleep(CYCLE)
        full = read_transcript()
        new = full[cursor:]
        if len(new) >= EXTRACT_MIN_NEW:
            try:
                with LOCK:
                    recent = [e["headline"] for e in STATE["events"][-RECENT_HEADLINES:]]
                evs = extract_events(new, recent, backfill=False)
                if evs:
                    add_events(evs, backfill=False)
                    print(f"+{len(evs)} post(s)", file=sys.stderr)
                with LOCK:
                    STATE["error"] = ""
                cursor = len(full)
            except Exception as e:  # noqa: BLE001
                with LOCK:
                    STATE["error"] = str(e)
                print(f"extract failed: {e}", file=sys.stderr)
        push_remote(live=True)


PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>D&D — live feed</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font:16px/1.55 -apple-system,system-ui,sans-serif;
         background:#13110f; color:#e8e1d4; height:100vh; display:flex; flex-direction:column; }
  header { padding:.6rem 1rem; border-bottom:1px solid #2a251e; display:flex;
           align-items:baseline; gap:.75rem; background:#1a1612; }
  header h1 { font-size:1rem; margin:0; font-weight:600; color:#d9b779; }
  header .meta { font-size:.78rem; color:#8a8073; margin-left:auto; }
  main { flex:1; display:grid; grid-template-columns: 1fr 26rem; min-height:0; }
  @media (max-width:820px){ main{ grid-template-columns:1fr; } #raw{ display:none; } }
  #raw { overflow-y:auto; padding:1.1rem 1.4rem; border-right:1px solid #2a251e; }
  #raw p { margin:0 0 .6rem; color:#b3aa9a; font-size:.9rem; }
  #raw p.marker { color:#d9b779; font-style:italic; text-align:center; }
  #feed { overflow-y:auto; padding:1rem 1.2rem; background:#171310; }
  .post { border-left:2px solid #4a3f2e; padding:.1rem 0 .9rem .9rem; margin:0 0 1rem; }
  .post.live { border-left-color:#7c2a1f; }
  .post .h { font-weight:600; color:#efb45a; margin:0 0 .25rem; }
  .post .b { margin:0; font-size:.93rem; }
  .post .t { font-size:.72rem; color:#6b6357; margin:.3rem 0 0; }
  .divider { text-align:center; color:#8a8073; font-size:.75rem; text-transform:uppercase;
             letter-spacing:.08em; margin:1.2rem 0; border-top:1px dashed #2a251e; padding-top:.8rem; }
</style></head>
<body>
  <header><h1>📡 Live feed</h1><span class="meta" id="meta">…</span></header>
  <main>
    <div id="raw"><p class="marker">transcript…</p></div>
    <div id="feed"></div>
  </main>
<script>
function esc(s){ const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }
async function tick(){
  try {
    const r = await fetch('/data'); const d = await r.json();
    const lines = (d.transcript||'').split('\\n').filter(x=>x.trim());
    document.getElementById('raw').innerHTML = lines.map(l =>
      l.startsWith('---') ? `<p class="marker">${esc(l.replace(/-/g,'').trim())}</p>` : `<p>${esc(l)}</p>`
    ).join('') || '<p class="marker">transcript…</p>';
    const evs = (d.events||[]).slice().sort((a,b)=>b.seq-a.seq);
    let html=''; let dividerDone=false;
    for (const e of evs){
      if (e.backfill && !dividerDone){ html += '<div class="divider">Earlier this session</div>'; dividerDone=true; }
      const t = e.at ? new Date(e.at*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '';
      html += `<div class="post ${e.at?'live':''}"><p class="h">${esc(e.headline)}</p>`+
              `<p class="b">${esc(e.body)}</p>${t?`<p class="t">${t}</p>`:''}</div>`;
    }
    document.getElementById('feed').innerHTML = html || '<p style="color:#8a8073">no posts yet…</p>';
    document.getElementById('meta').textContent = evs.length + ' posts';
  } catch(e){ document.getElementById('meta').textContent='reconnecting…'; }
}
tick(); setInterval(tick, 3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/data":
            with LOCK:
                payload = {
                    "transcript": read_transcript(),
                    "events": STATE["events"],
                    "error": STATE["error"],
                }
            self._send(200, "application/json", json.dumps(payload).encode())
        else:
            self._send(200, "text/html; charset=utf-8", PAGE.encode())


def main():
    import atexit
    import signal

    threading.Thread(target=feed_loop, daemon=True).start()

    push_on = bool(LIVE_PUSH_URL and LIVE_PUSH_TOKEN)
    if push_on:
        atexit.register(lambda: push_remote(live=False))
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    has_key = bool(os.environ.get("DEEPSEEK_API_KEY"))
    print(f"serving {LIVE_TXT.name} on http://0.0.0.0:{PORT}  "
          f"(posts: {'on' if has_key else 'OFF — set DEEPSEEK_API_KEY'}; "
          f"remote: {'on' if push_on else 'off'})", file=sys.stderr)
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
