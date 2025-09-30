from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue, Empty
from typing import Any, Dict, List, Tuple

import boto3
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

# Load environment variables
load_dotenv()

# -------------------- Config --------------------
PORT = int(os.environ.get("PORT", 5005))
BANNER_DURATION_MS = int(os.environ.get("BANNER_DURATION_MS", 8000))
DATA_FILE = Path(os.environ.get("DATA_FILE", "landings.json")).resolve()
QUOTES_FILE = Path("quotes.json").resolve()

# AWS Polly Configuration
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
POLLY_VOICE_ID = os.environ.get("POLLY_VOICE_ID", "Joanna")
POLLY_OUTPUT_FORMAT = os.environ.get("POLLY_OUTPUT_FORMAT", "mp3")

# Score messages (PG & sassy)
SCORE_MESSAGES = {
    1: "Mayday? That was… educational.",
    2: "Hard arrival. Teeth still rattling.",
    3: "Firm. The landing gear filed a complaint.",
    4: "Not bad, not smooth. We felt it.",
    5: "Acceptable. Coffee only trembled.",
    6: "Decent touch. Cabin crew kept pouring.",
    7: "Nice! Most passengers missed it.",
    8: "Smooth operator. Butter adjacent.",
    9: "Greased it. Polite applause engaged.",
    10: "Absolute butter. Chief pilot approved!",
}


def level_for_score(score: int) -> str:
    if score <= 3:
        return "bad"  # red
    if score <= 6:
        return "ok"  # amber
    if score <= 8:
        return "good"  # yellow
    return "great"  # green


# -------------------- Quotes & Polly --------------------
def load_quotes() -> Dict[str, List[str]]:
    """Load quotes from JSON file."""
    try:
        with open(QUOTES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('quotes', {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_random_quote(score: int) -> str:
    """Get a random sarcastic quote based on the score."""
    quotes = load_quotes()
    score_quotes = quotes.get(str(score), [])
    if score_quotes:
        return random.choice(score_quotes)
    return "Well, that happened."


def generate_audio_url(text: str) -> str:
    """Generate audio using Amazon Polly and return the audio URL."""
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        return ""
    
    try:
        # Create consistent filename based on text content hash
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()[:12]
        audio_filename = f"quote_{text_hash}.{POLLY_OUTPUT_FORMAT}"
        audio_path = Path("static") / audio_filename
        
        # Check if audio file already exists
        if audio_path.exists():
            return f"/static/{audio_filename}"
        
        # Initialize Polly client
        polly_client = boto3.client(
            'polly',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        
        # Generate speech
        response = polly_client.synthesize_speech(
            Text=text,
            OutputFormat=POLLY_OUTPUT_FORMAT,
            VoiceId=POLLY_VOICE_ID
        )
        
        # Save audio to static folder
        audio_path.parent.mkdir(exist_ok=True)
        
        with open(audio_path, 'wb') as f:
            f.write(response['AudioStream'].read())
        
        return f"/static/{audio_filename}"
    except Exception as e:
        print(f"Error generating audio: {e}")
        return ""


# -------------------- Persistence --------------------
class DataStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not self.path.exists():
            self._atomic_write({"landings": []})
            return
        # If corrupt, recreate
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "landings" not in data or not isinstance(data["landings"], list):
                raise ValueError("Invalid structure")
        except Exception:
            self._atomic_write({"landings": []})

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)  # atomic on same filesystem

    def _read(self) -> Dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def append(self, score: int, ts: str) -> None:
        with self.lock:
            try:
                data = self._read()
            except Exception:
                data = {"landings": []}
            data.setdefault("landings", []).append({"score": int(score), "ts": ts})
            self._atomic_write(data)

    def reset(self) -> None:
        with self.lock:
            self._atomic_write({"landings": []})

    def get_landings(self) -> List[Dict[str, Any]]:
        with self.lock:
            try:
                data = self._read()
            except Exception:
                data = {"landings": []}
            landings = data.get("landings", [])
            if not isinstance(landings, list):
                return []
            return landings


# -------------------- Stats --------------------
def compute_stats(landings: List[Dict[str, Any]]) -> Dict[str, Any]:
    scores = [int(x.get("score", 0)) for x in landings]
    count = len(scores)
    average = round(sum(scores) / count, 2) if count else 0.0
    best = max(scores) if scores else 0

    # recent: last 10 scores, newest -> oldest
    recent = list(reversed(scores[-10:]))

    # top 5: by score desc; ties keep earlier entry first (lower original index)
    indexed = list(enumerate(scores))
    indexed.sort(key=lambda t: (-t[1], t[0]))
    top = [score for (_idx, score) in indexed[:5]]

    return {
        "count": count,
        "average": average,
        "best": best,
        "recent": recent,
        "top": top,
    }


# -------------------- SSE Hub --------------------
class SSEHub:
    def __init__(self):
        self.clients: List[Queue] = []
        self.lock = threading.Lock()

    def register(self) -> Queue:
        q: Queue = Queue()
        with self.lock:
            self.clients.append(q)
        return q

    def unregister(self, q: Queue) -> None:
        with self.lock:
            try:
                self.clients.remove(q)
            except ValueError:
                pass

    def broadcast(self, payload: Dict[str, Any]) -> None:
        with self.lock:
            clients_snapshot = list(self.clients)
        for q in clients_snapshot:
            try:
                q.put_nowait(payload)
            except Exception:
                # If a queue is full/broken, drop the message for that client
                pass


hub = SSEHub()
store = DataStore(DATA_FILE)


def utc_now_iso() -> str:
    # ISO8601 UTC with Z suffix
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sse_format(data: Dict[str, Any]) -> str:
    return f"data: {json.dumps(data, separators=(',', ':'))}\n\n"


# -------------------- Flask app --------------------
app = Flask(__name__, static_folder="static", template_folder="templates")


@app.get("/overlay")
def overlay_page() -> Response:
    return Response(render_template("overlay.html", banner_duration_ms=BANNER_DURATION_MS), mimetype="text/html")


@app.get("/stats")
def stats() -> Response:
    landings = store.get_landings()
    return jsonify(compute_stats(landings))


@app.get("/stream")
def stream() -> Response:
    q = hub.register()

    def gen():
        # Send minimal hello (no stats)
        hello = {"type": "hello"}
        yield sse_format(hello)
        try:
            while True:
                try:
                    item = q.get(timeout=60)
                except Empty:
                    # Keep-alive comment to prevent some proxies from closing the connection
                    yield ": keep-alive\n\n"
                    continue
                yield sse_format(item)
        except GeneratorExit:
            pass
        finally:
            hub.unregister(q)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # for nginx, harmless otherwise
        "Connection": "keep-alive",
    }
    return Response(gen(), mimetype="text/event-stream", headers=headers)


@app.get("/vote/<int:score>")
def vote(score: int) -> Response:
    # Clamp 1..10
    clamped = max(1, min(10, int(score)))
    ts = utc_now_iso()
    
    # Get random quote and generate audio
    quote = get_random_quote(clamped)
    audio_url = generate_audio_url(quote)
    
    payload = {
        "type": "vote",
        "score": clamped,
        "message": SCORE_MESSAGES.get(clamped, ""),
        "quote": quote,
        "audio_url": audio_url,
        "level": level_for_score(clamped),
        "duration_ms": BANNER_DURATION_MS,
        "ts": ts,
    }
    hub.broadcast(payload)
    return jsonify(payload)


@app.post("/reset")
def reset() -> Response:
    # No-op for Option B; broadcast a minimal hello
    hello = {"type": "hello"}
    hub.broadcast(hello)
    return jsonify({"ok": True})


@app.get("/")
def root() -> Response:
    # convenience redirect to overlay
    return overlay_page()


if __name__ == "__main__":
    # Set console window title
    os.system("title Landing Voting System - Server Running")
    
    # Print console heading
    print("=" * 60)
    print("🛬 LANDING VOTING SYSTEM")
    print("=" * 60)
    print(f"🌐 Server starting on: http://127.0.0.1:{PORT}")
    print(f"📺 Overlay URL: http://127.0.0.1:{PORT}/overlay")
    print(f"📊 Stats URL: http://127.0.0.1:{PORT}/stats")
    print("=" * 60)
    print("Ready to receive votes! Use: curl http://127.0.0.1:5005/vote/[1-10]")
    print("=" * 60)
    print()
    
    # For development. In production, use a proper WSGI server.
    # threaded=True allows handling SSE + requests concurrently.
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
