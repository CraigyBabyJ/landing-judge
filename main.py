"""Landing Judge — local overlay + API + TTS + desktop UI.

- Overlay: `/overlay` streamed via SSE, fixed client-side display time.
- API: `GET /vote/<score>` emits score, tier level, quote, optional audio.
- TTS: Amazon Polly integration with audio effects and noise beds.
- UI: PySide6 control panel to edit `.env`, test votes, and tweak audio.

This module hosts the Flask app, SSE hub, audio index utilities,
and the PySide6 desktop UI class.
"""
import sys
import os
import json
import threading
import hashlib
import itertools
from pathlib import Path
from queue import Queue, Empty
import time

import requests
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv, dotenv_values, set_key
from flask import Flask, Response, jsonify, render_template, request

from PySide6.QtCore import QTimer, Qt, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QDialog,
    QMessageBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QTextEdit,
)

# -------------------- Optional Debug Console --------------------
def _enable_debug_console_if_requested() -> None:
    """On Windows, open a console window when --debug or -d is passed.

    This lets a windowed build (made with PyInstaller --noconsole) still
    show prints/logs when explicitly requested at runtime.
    """
    try:
        # Only relevant on Windows
        if not sys.platform.startswith('win'):
            return
        argv = list(sys.argv) if sys.argv else []
        if not any(a in ('--debug', '-d') for a in argv):
            return
        # Strip the flag so Qt/Flask don't see it
        try:
            sys.argv = [a for a in argv if a not in ('--debug', '-d')]
        except Exception:
            pass
        # Allocate a new console and wire stdio to it
        try:
            import ctypes
            ctypes.windll.kernel32.AllocConsole()
            try:
                ctypes.windll.kernel32.SetConsoleTitleW("LandingJudge Debug Console")
            except Exception:
                pass
            # Bind Python stdio to the console device files
            try:
                sys.stdout = open('CONOUT$', 'w', buffering=1, encoding='utf-8', errors='replace')
                sys.stderr = open('CONOUT$', 'w', buffering=1, encoding='utf-8', errors='replace')
            except Exception:
                pass
            try:
                sys.stdin = open('CONIN$', 'r', encoding='utf-8', errors='replace')
            except Exception:
                pass
            print("[debug] Console enabled. Runtime logs will appear here.")
        except Exception:
            # If anything goes wrong, continue without console
            pass
    except Exception:
        pass

# -------------------- Environment --------------------
load_dotenv()
ENV_PATH = Path('.env')

PORT = int(os.environ.get('PORT', 5005))
BANNER_DURATION_MS = int(os.environ.get('BANNER_DURATION_MS', 8000))
BANNER_MIN_LINGER_MS = int(os.environ.get('BANNER_MIN_LINGER_MS', 2000))
QUOTES_FILE = Path('quotes.json').resolve()
# Default quotes/messages bundled with the app
DEFAULT_QUOTES_FILE = Path(os.path.join(os.path.dirname(__file__), 'quotes.default.json')).resolve()
# Store audio index and files under static/audio/
AUDIO_INDEX_PATH = Path('static/audio/audio_index.json').resolve()
OVERLAY_HUE_DEG = int(os.environ.get('OVERLAY_HUE_DEG', '0'))

AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
POLLY_VOICE_ID = os.environ.get('POLLY_VOICE_ID', 'Joanna')
POLLY_OUTPUT_FORMAT = os.environ.get('POLLY_OUTPUT_FORMAT', 'mp3')
ENABLE_TTS = os.environ.get('ENABLE_TTS', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
ADD_STATIC_NOISE = os.environ.get('ADD_STATIC_NOISE', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
# Control visibility of the live events (SSE) log panel
SHOW_EVENTS_LOG = os.environ.get('SHOW_EVENTS_LOG', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
# Overlay audio effect preset selection
EFFECT_PRESET = os.environ.get('EFFECT_PRESET', 'none').strip().lower()
# Whether the banner should hide immediately when audio ends (otherwise only by duration)
HIDE_ON_AUDIO_END = os.environ.get('HIDE_ON_AUDIO_END', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
# Ding Dong bell playback toggle
ENABLE_DINGDONG = os.environ.get('ENABLE_DINGDONG', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
# Noise level settings for effects
def _safe_float(val: str, default: float) -> float:
    try:
        return float(val)
    except Exception:
        return default

STATIC_NOISE_LEVEL = _safe_float(os.environ.get('STATIC_NOISE_LEVEL', '0.02'), 0.02)
RADIO_NOISE_LEVEL = _safe_float(os.environ.get('RADIO_NOISE_LEVEL', '0.03'), 0.03)
WIND_NOISE_LEVEL = _safe_float(os.environ.get('WIND_NOISE_LEVEL', '0.03'), 0.03)
# Social links for header
# Updated to user's requested links and added website
WEBSITE_URL = os.environ.get('WEBSITE_URL', 'https://www.craigybabyj.com')
DISCORD_URL = os.environ.get('DISCORD_URL', 'https://discord.gg/F7HYUB2uGu')
TIKTOK_URL = os.environ.get('TIKTOK_URL', 'https://tiktok.com/@craigybabyj_new')


def load_env():
    return dotenv_values(str(ENV_PATH))


def save_env_var(key: str, value: str):
    set_key(str(ENV_PATH), key, value)


# -------------------- Quotes and Messages --------------------
def level_for_score(score: int) -> str:
    if score <= 3:
        return 'bad'
    if score <= 6:
        return 'ok'
    if score <= 8:
        return 'good'
    return 'great'


def _load_default_quotes_payload() -> dict:
    """Load the bundled default quotes/messages, with a minimal fallback."""
    try:
        with open(DEFAULT_QUOTES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {
            "quotes": {
                "1": ["Well, that was... educational.", "Physics called—they want an explanation."],
                "2": ["Hard arrival. Teeth still rattling."],
                "3": ["Firm. The landing gear filed a complaint."],
                "4": ["Not bad, not smooth. We felt it."],
                "5": ["Acceptable. Coffee only trembled."],
                "6": ["Decent touch. Cabin crew kept pouring."],
                "7": ["Nice! Most passengers missed it."],
                "8": ["Smooth operator. Butter adjacent."],
                "9": ["Greased it. Polite applause engaged."],
                "10": ["Absolute butter.", "Chief pilot approved!"]
            },
            "messages": {
                "1": "Mayday? That was… educational.",
                "2": "Hard arrival. Teeth still rattling.",
                "3": "Firm. The landing gear filed a complaint.",
                "4": "Not bad, not smooth. We felt it.",
                "5": "Acceptable. Coffee only trembled.",
                "6": "Decent touch. Cabin crew kept pouring.",
                "7": "Nice! Most passengers missed it.",
                "8": "Smooth operator. Butter adjacent.",
                "9": "Greased it. Polite applause engaged.",
                "10": "Absolute butter. Chief pilot approved!"
            }
        }


def load_messages() -> dict:
    """Load messages, merging user overrides on top of defaults."""
    defaults = _load_default_quotes_payload().get('messages', {})
    user_msgs = {}
    try:
        with open(QUOTES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        user_msgs = data.get('messages', {})
    except Exception:
        user_msgs = {}
    merged = {str(k): str(v) for k, v in defaults.items()}
    for k, v in user_msgs.items():
        merged[str(k)] = str(v)
    return merged


def load_quotes() -> dict:
    """Load quotes, merging user overrides on top of defaults.

    Ensures that missing scores in user quotes fall back to the bundled defaults,
    so the EXE always has a full set even if quotes.json is trimmed.
    """
    defaults = _load_default_quotes_payload().get('quotes', {})
    user_quotes = {}
    try:
        with open(QUOTES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        user_quotes = data.get('quotes', {})
    except Exception:
        user_quotes = {}
    # Merge: defaults first, then overlay user-provided lists
    merged = {}
    # Normalize keys as strings
    for k, v in defaults.items():
        try:
            merged[str(k)] = list(v) if isinstance(v, list) else []
        except Exception:
            merged[str(k)] = []
    for k, v in user_quotes.items():
        try:
            merged[str(k)] = list(v) if isinstance(v, list) else merged.get(str(k), [])
        except Exception:
            pass
    return merged


# -------------------- Voice Labels --------------------
def flag_for_lang(code: str) -> str:
    try:
        code = (code or '').lower()
        region = None
        if '-' in code:
            parts = code.split('-')
            region = parts[-1]
        flags = {
            'us': '🇺🇸', 'gb': '🇬🇧', 'uk': '🇬🇧', 'au': '🇦🇺', 'nz': '🇳🇿', 'ca': '🇨🇦', 'ie': '🇮🇪', 'za': '🇿🇦',
            'in': '🇮🇳', 'sg': '🇸🇬', 'ph': '🇵🇭',
            'es': '🇪🇸', 'mx': '🇲🇽', 'ar': '🇦🇷', 'cl': '🇨🇱', 'co': '🇨🇴',
            'fr': '🇫🇷', 'de': '🇩🇪', 'it': '🇮🇹', 'pt': '🇵🇹', 'br': '🇧🇷',
            'nl': '🇳🇱', 'pl': '🇵🇱', 'ru': '🇷🇺', 'sv': '🇸🇪', 'no': '🇳🇴', 'da': '🇩🇰', 'fi': '🇫🇮', 'tr': '🇹🇷',
            'ja': '🇯🇵', 'ko': '🇰🇷', 'zh': '🇨🇳', 'tw': '🇹🇼',
            'sa': '🇸🇦', 'ae': '🇦🇪', 'il': '🇮🇱'
        }
        return flags.get(region, '')
    except Exception:
        return ''


def voice_label(voice_id: str, language_name: str, language_code: str) -> str:
    flag = flag_for_lang(language_code)
    return f"{flag} {voice_id}" if flag else voice_id


def _regional_indicator_code(ch: str) -> str:
    base = ord('a')
    idx = ord(ch.lower()) - base
    # U+1F1E6 is 'A' regional indicator
    return hex(0x1F1E6 + idx)[2:]


def _twemoji_hex_for_country(country: str) -> str:
    if not country or len(country) != 2:
        return ''
    return f"{_regional_indicator_code(country[0])}-{_regional_indicator_code(country[1])}"


def flag_icon_for_lang(language_code: str) -> QIcon:
    try:
        code = (language_code or '').lower()
        region = code.split('-')[-1] if '-' in code else code
        flags_dir = Path('static/flags')
        flags_dir.mkdir(parents=True, exist_ok=True)
        png_path = flags_dir / f"{region}.png"
        if not png_path.exists():
            # Attempt to download a small PNG from Twemoji CDN
            hex_seq = _twemoji_hex_for_country(region)
            if hex_seq:
                url = f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{hex_seq}.png"
                try:
                    import requests as _rq
                    r = _rq.get(url, timeout=6)
                    if r.status_code == 200:
                        png_path.write_bytes(r.content)
                except Exception:
                    pass
        if png_path.exists():
            pix = QPixmap(str(png_path))
            if not pix.isNull():
                return QIcon(pix)
    except Exception:
        pass
    return QIcon()


def _lang_region(code: str) -> str:
    try:
        code = (code or '').lower()
        if '-' in code:
            return code.split('-')[-1]
        return code
    except Exception:
        return ''


def voice_priority(language_code: str) -> int:
    region = _lang_region(language_code)
    if region in {'gb', 'uk'}:
        return 0
    if region in {'au', 'nz', 'ie', 'za'}:
        return 1
    return 2


def list_region_voices(polly):
    """List voices available in the current region with supported engines.

    Returns entries like:
    {
      "Id": "Joanna",
      "LanguageName": "US English",
      "LanguageCode": "en-US",
      "SupportedEngines": ["standard", "neural"]
    }
    """
    voices = {}

    def page(engine: str):
        try:
            paginator = polly.get_paginator('describe_voices')
            for p in paginator.paginate(Engine=engine):
                for v in p.get('Voices', []):
                    yield {
                        'Id': v.get('Id'),
                        'LanguageName': v.get('LanguageName', ''),
                        'LanguageCode': v.get('LanguageCode', ''),
                        'Engine': engine,
                    }
        except Exception:
            # If engine not supported in region, skip
            return

    for rec in itertools.chain(page('standard'), page('neural')):
        vid = rec.get('Id')
        if not vid:
            continue
        entry = voices.setdefault(
            vid,
            {
                'Id': vid,
                'LanguageName': rec.get('LanguageName', ''),
                'LanguageCode': rec.get('LanguageCode', ''),
                'SupportedEngines': set(),
            },
        )
        entry['SupportedEngines'].add(rec.get('Engine'))

    catalog = []
    for v in voices.values():
        catalog.append({**v, 'SupportedEngines': sorted(list(v['SupportedEngines']))})
    return catalog


def build_polly(region: str):
    try:
        return boto3.client(
            'polly',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=region,
        )
    except Exception:
        # Fallback without explicit creds if env/instance profile is used
        return boto3.client('polly', region_name=region)


def pick_engine_for_voice(voice_id: str, catalog):
    try:
        vmap = {v.get('Id'): v for v in catalog}
        v = vmap.get(voice_id)
        engines = (v.get('SupportedEngines') if v else []) or []
        return 'neural' if 'neural' in engines else 'standard'
    except Exception:
        return 'standard'

def sanitize_voice_id(raw_voice: str, catalog):
    s = (raw_voice or '').strip()
    if not s:
        return ""
    # Exact match against catalog Ids
    ids = {v.get('Id') for v in catalog if v.get('Id')}
    if s in ids:
        return s
    # Substring match for rich labels containing the Id (e.g., "🇬🇧 Emma • Natural")
    for vid in ids:
        if vid and vid in s:
            return vid
    # Fallback: pick longest alphabetic token
    tokens = [t for t in s.replace('•', ' ').replace('·', ' ').split() if t.isalpha()]
    return max(tokens, key=len) if tokens else s


def get_random_quote(score: int) -> str:
    try:
        quotes = load_quotes()
        score_quotes = quotes.get(str(score), [])
        if score_quotes:
            import random
            return random.choice(score_quotes)
        # Fallback to a generic line if no quote for score
        return "Well, that happened."
    except Exception:
        return "Well, that happened."


MESSAGES = load_messages()


# -------------------- UI Styling --------------------
def ui_stylesheet() -> str:
    # Modern dark theme with an azure accent
    return """
    QMainWindow, QWidget {
        background-color: #101318;
        color: #E6E8EB;
        font-size: 10pt;
    }
    QGroupBox {
        border: 1px solid #2A2F3A;
        border-radius: 8px;
        margin-top: 12px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: #9DBFFB;
        font-weight: 600;
    }
    QLabel { color: #CFD3D8; }
    QLabel#statusLabel {
        background: #182030;
        border: 1px solid #294067;
        border-radius: 6px;
        padding: 6px 8px;
        color: #A8D1FF;
    }
    QSpinBox, QComboBox, QLineEdit {
        background-color: #0F1320;
        border: 1px solid #2A3347;
        border-radius: 6px;
        padding: 4px 6px;
        selection-background-color: #27406B;
        color: #E6E8EB;
    }
    QComboBox::drop-down { width: 20px; }
    QTextEdit {
        background-color: #0D111A;
        border: 1px solid #2A3347;
        border-radius: 6px;
        padding: 6px;
        color: #CFD3D8;
    }
    QPushButton {
        background-color: #1B2130;
        border: 1px solid #2F3A4F;
        border-radius: 6px;
        padding: 6px 10px;
        color: #E6E8EB;
    }
    QPushButton:hover { background-color: #253047; }
    QPushButton:pressed { background-color: #1A2538; }
    QCheckBox { spacing: 8px; }
    /* Ensure the checkbox indicator visibly reflects checked state */
    QCheckBox::indicator {
        width: 18px; height: 18px;
        border: 1px solid #2F3A4F;
        border-radius: 4px;
        background-color: #0F1320;
        margin-right: 6px;
    }
    QCheckBox::indicator:hover { border-color: #4A5A75; }
    QCheckBox::indicator:checked {
        background-color: #3A86FF;
        border-color: #5EA0FF;
    }
    QCheckBox::indicator:unchecked {
        background-color: #0F1320;
    }
    QCheckBox::indicator:disabled { opacity: 0.5; }
    QToolTip {
        background-color: #1B2130;
        color: #E6E8EB;
        border: 1px solid #2F3A4F;
        border-radius: 6px;
        padding: 6px;
    }
    """


def generate_audio_url(text: str) -> str:
    # Respect the user's toggle - reload .env and override existing process env so changes apply live
    load_dotenv(override=True)  # Reload .env and override os.environ
    tts_enabled = os.environ.get('ENABLE_TTS', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
    if not tts_enabled:
        return ""
    try:
        # Resolve voice and engine for region. Use AWS default credential chain if
        # explicit env keys are not provided, so profiles/SSO still work.
        vid_raw = (POLLY_VOICE_ID or '').strip()
        if not vid_raw:
            return ""
        polly_client = build_polly(AWS_REGION)
        catalog = list_region_voices(polly_client)
        vid = sanitize_voice_id(vid_raw, catalog)
        engine = pick_engine_for_voice(vid, catalog)

        # Create consistent filename based on text content hash
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()[:12]
        safe_voice = ''.join(c for c in vid if c.isalnum() or c in ('-', '_'))
        audio_filename = f"quote_{safe_voice}_{engine}_{text_hash}.{POLLY_OUTPUT_FORMAT}"
        audio_path = Path(app.static_folder) / 'audio' / audio_filename

        # Load index and reuse if present (engine-aware)
        index = {}
        if AUDIO_INDEX_PATH.exists():
            try:
                with open(AUDIO_INDEX_PATH, 'r', encoding='utf-8') as f:
                    index = json.load(f)
            except Exception:
                index = {}
        key_material = f"{text}|voice={vid}|engine={engine}|fmt={POLLY_OUTPUT_FORMAT}|region={AWS_REGION}"
        key_hash = hashlib.md5(key_material.encode('utf-8')).hexdigest()[:12]
        entry = index.get(key_hash)
        if entry:
            # Prefer new location; fall back to legacy path for backwards compatibility
            existing_new = Path(app.static_folder) / 'audio' / entry.get('filename', '')
            existing_old = Path(app.static_folder) / entry.get('filename', '')
            if existing_new.exists():
                return f"/static/audio/{entry['filename']}"
            if existing_old.exists():
                return f"/static/{entry['filename']}"

        # Not in index (or file missing) — synthesize and record
        try:
            resp = polly_client.synthesize_speech(
                Text=text,
                OutputFormat=POLLY_OUTPUT_FORMAT,
                VoiceId=vid,
                Engine=engine,
            )
        except ClientError:
            # Retry once with alternate engine on mismatch
            alt = 'standard' if engine == 'neural' else 'neural'
            try:
                resp = polly_client.synthesize_speech(
                    Text=text,
                    OutputFormat=POLLY_OUTPUT_FORMAT,
                    VoiceId=vid,
                    Engine=alt,
                )
                engine = alt
                audio_filename = f"quote_{safe_voice}_{engine}_{text_hash}.{POLLY_OUTPUT_FORMAT}"
                audio_path = Path(app.static_folder) / 'audio' / audio_filename
                # Recompute key for alt engine
                key_material = f"{text}|voice={vid}|engine={engine}|fmt={POLLY_OUTPUT_FORMAT}|region={AWS_REGION}"
                key_hash = hashlib.md5(key_material.encode('utf-8')).hexdigest()[:12]
            except ClientError:
                return ""

        audio_path.parent.mkdir(parents=True, exist_ok=True)
        with open(audio_path, 'wb') as f:
            f.write(resp['AudioStream'].read())

        # Persist index entry with play_count initialized to 0
        index[key_hash] = {
            'text': text,
            'voice': vid,
            'engine': engine,
            'format': POLLY_OUTPUT_FORMAT,
            'region': AWS_REGION,
            'filename': audio_filename,
            'created_ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'play_count': 0,
        }
        try:
            AUDIO_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(AUDIO_INDEX_PATH, 'w', encoding='utf-8') as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return f"/static/audio/{audio_filename}"
    except Exception:
        # If anything goes wrong (including missing credentials), return no audio
        return ""


def _increment_audio_play(text: str) -> None:
    try:
        vid_raw = (POLLY_VOICE_ID or '').strip()
        polly_client = build_polly(AWS_REGION)
        catalog = list_region_voices(polly_client)
        vid = sanitize_voice_id(vid_raw, catalog)
        engine = pick_engine_for_voice(vid, catalog)
        key_material = f"{text}|voice={vid}|engine={engine}|fmt={POLLY_OUTPUT_FORMAT}|region={AWS_REGION}"
        key_hash = hashlib.md5(key_material.encode('utf-8')).hexdigest()[:12]
        index = {}
        if AUDIO_INDEX_PATH.exists():
            with open(AUDIO_INDEX_PATH, 'r', encoding='utf-8') as f:
                index = json.load(f)
        entry = index.get(key_hash)
        if entry:
            entry['play_count'] = int(entry.get('play_count', 0)) + 1
            with open(AUDIO_INDEX_PATH, 'w', encoding='utf-8') as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# -------------------- SSE Hub --------------------
class SSEHub:
    def __init__(self):
        self.clients: list[Queue] = []
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

    def broadcast(self, payload: dict) -> None:
        with self.lock:
            clients = list(self.clients)
        for q in clients:
            try:
                q.put_nowait(payload)
            except Exception:
                pass


hub = SSEHub()


def sse_format(data: dict) -> str:
    return f"data: {json.dumps(data, separators=(',', ':'))}\n\n"


# -------------------- Flask App --------------------
app = Flask(__name__, static_folder='static', template_folder='templates')

# Ensure audio index path aligns with Flask's static folder at runtime (e.g., PyInstaller)
# This overrides the earlier default to prevent mismatches between write/read locations.
AUDIO_INDEX_PATH = Path(app.static_folder) / 'audio' / 'audio_index.json'


@app.get('/overlay')
def overlay_page():
    try:
        from flask import render_template
    except Exception:
        pass
    return Response(
        render_template(
            'overlay.html',
            overlay_hue_deg=OVERLAY_HUE_DEG,
        ),
        mimetype='text/html'
    )

@app.post('/theme')
def update_theme():
    """Update overlay hue from frontend; persist and broadcast via SSE."""
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}
    try:
        deg = int(data.get('hue_deg', 0))
    except Exception:
        deg = 0
    # Clamp to [0, 360]
    deg = max(0, min(360, deg))
    try:
        save_env_var('OVERLAY_HUE_DEG', str(deg))
    except Exception:
        pass
    # Update in-memory value
    try:
        global OVERLAY_HUE_DEG
        OVERLAY_HUE_DEG = deg
    except Exception:
        pass
    # Broadcast to SSE listeners
    try:
        hub.broadcast({'type': 'theme', 'hue_deg': deg})
    except Exception:
        pass
    return jsonify({'ok': True, 'hue_deg': deg})


@app.post('/preview')
def overlay_preview():
    """Toggle overlay preview mode (show 1/10 without quotes)."""
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}
    try:
        active = bool(data.get('active', False))
    except Exception:
        active = False
    try:
        score = int(data.get('score', 1))
    except Exception:
        score = 1
    score = max(1, min(10, score))
    try:
        hub.broadcast({'type': 'preview', 'active': active, 'score': score})
    except Exception:
        pass
    return jsonify({'ok': True, 'active': active, 'score': score})


@app.get('/stream')
def stream():
    q = hub.register()

    def gen():
        yield sse_format({'type': 'hello'})
        try:
            while True:
                try:
                    item = q.get(timeout=60)
                except Empty:
                    yield ": keep-alive\n\n"
                    continue
                yield sse_format(item)
        except GeneratorExit:
            pass
        finally:
            hub.unregister(q)

    headers = {
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive',
    }
    return Response(gen(), mimetype='text/event-stream', headers=headers)


@app.get('/vote/<int:score>')
def vote(score: int):
    """Handle a vote for a landing score (1–10).

    - Picks a random quote for the clamped score.
    - Generates/looks up audio URL if TTS is enabled.
    - Broadcasts an event with score, tier, quote, audio, and effects.
    - Includes a `message` field useful for logs/API consumers; overlay
      currently displays only the `quote` text and plays audio.
    """
    clamped = max(1, min(10, int(score)))
    quote = get_random_quote(clamped)
    # Check TTS state from environment directly instead of relying on global variable
    # Ensure we override existing process env so UI-saved changes apply without restart
    load_dotenv(override=True)  # Reload .env and override os.environ
    tts_enabled = os.environ.get('ENABLE_TTS', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
    dingdong_enabled = os.environ.get('ENABLE_DINGDONG', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
    # Hard guard: do not generate or use cached audio when TTS is disabled
    audio_url = ""
    if tts_enabled:
        audio_url = generate_audio_url(quote)
        if audio_url:
            _increment_audio_play(quote)
    payload = {
        'type': 'vote',
        'enable_tts': bool(tts_enabled),
        'enable_dingdong': bool(dingdong_enabled),
        'score': clamped,
        'message': MESSAGES.get(str(clamped), ''),
        'quote': quote,
        'audio_url': audio_url,
        'level': level_for_score(clamped),
        'duration_ms': BANNER_DURATION_MS,
        'effects': {
            'static_noise': bool(ADD_STATIC_NOISE),
            'preset': str(EFFECT_PRESET or 'none'),
            # Per-effect noise levels
            'static_noise_level': float(STATIC_NOISE_LEVEL or 0.0),
            'radio_noise_level': float(RADIO_NOISE_LEVEL or 0.0),
            'wind_noise_level': float(WIND_NOISE_LEVEL or 0.0),
        },
        'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    hub.broadcast(payload)
    return jsonify(payload)


@app.get('/')
def root():
    return overlay_page()


def start_server(port: int):
    # Print helpful info to console
    print('============================================================')
    print('🛬 LANDING JUDGE')
    print('============================================================')
    print(f'🌐 Server starting on: http://127.0.0.1:{port}')
    print(f'📺 Overlay URL:      http://127.0.0.1:{port}/overlay')
    print('============================================================')
    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)


# -------------------- PySide6 UI --------------------
class AllInOneUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Landing Judge - by CraigyBabyJ')
        # Set window/taskbar icon from the bundled static folder (works in EXE and dev)
        try:
            icon_path = Path(app.static_folder) / 'icons' / 'icon.png'
            if not icon_path.exists():
                icon_path = Path('static/icons/icon.png')
            if icon_path.exists():
                ic = QIcon(str(icon_path))
                self.setWindowIcon(ic)
                try:
                    QApplication.instance().setWindowIcon(ic)
                except Exception:
                    pass
        except Exception:
            pass
        self.env = load_env()
        self.default_port = int(self.env.get('PORT', str(PORT)) or PORT)
        self.default_banner_ms = int(self.env.get('BANNER_DURATION_MS', str(BANNER_DURATION_MS)) or BANNER_DURATION_MS)
        self.default_min_linger_ms = int(self.env.get('BANNER_MIN_LINGER_MS', str(BANNER_MIN_LINGER_MS)) or BANNER_MIN_LINGER_MS)
        # Default for hide-on-audio-end; Extra time display is the inverse
        try:
            self.default_hide_on_audio_end = self.env.get('HIDE_ON_AUDIO_END', 'true').strip().lower() in {'1','true','yes','on'}
        except Exception:
            self.default_hide_on_audio_end = True
        self.default_region = self.env.get('AWS_REGION', AWS_REGION)
        self.default_voice = self.env.get('POLLY_VOICE_ID', POLLY_VOICE_ID)
        self.default_format = self.env.get('POLLY_OUTPUT_FORMAT', POLLY_OUTPUT_FORMAT)
        self.default_tts = ENABLE_TTS
        self.default_static_noise = self.env.get('ADD_STATIC_NOISE', 'false').strip().lower() in {'1','true','yes','on'}
        # Ding Dong enable default
        try:
            self.default_dingdong = self.env.get('ENABLE_DINGDONG', 'false').strip().lower() in {'1','true','yes','on'}
        except Exception:
            self.default_dingdong = False
        # Default noise levels
        try:
            self.default_static_level = float(self.env.get('STATIC_NOISE_LEVEL', str(STATIC_NOISE_LEVEL)))
        except Exception:
            self.default_static_level = STATIC_NOISE_LEVEL
        try:
            self.default_radio_level = float(self.env.get('RADIO_NOISE_LEVEL', str(RADIO_NOISE_LEVEL)))
        except Exception:
            self.default_radio_level = RADIO_NOISE_LEVEL
        try:
            self.default_wind_level = float(self.env.get('WIND_NOISE_LEVEL', str(WIND_NOISE_LEVEL)))
        except Exception:
            self.default_wind_level = WIND_NOISE_LEVEL
        # Runtime copies that the slider will modify
        self.static_noise_level = self.default_static_level
        self.radio_noise_level = self.default_radio_level
        self.wind_noise_level = self.default_wind_level
        self.default_key_id = self.env.get('AWS_ACCESS_KEY_ID', AWS_ACCESS_KEY_ID or '')
        self.default_secret = self.env.get('AWS_SECRET_ACCESS_KEY', AWS_SECRET_ACCESS_KEY or '')
        # Default for showing the events log (SSE)
        try:
            self.default_show_events = self.env.get('SHOW_EVENTS_LOG', 'true').strip().lower() in {'1','true','yes','on'}
        except Exception:
            self.default_show_events = True
        # Overlay hue default (degrees)
        try:
            self.default_hue = int(self.env.get('OVERLAY_HUE_DEG', str(OVERLAY_HUE_DEG or 0)))
        except Exception:
            self.default_hue = 0
        # Track current hue without exposing a spinbox in UI
        self.current_hue_deg = self.default_hue
        self.events_queue: Queue = Queue()

        self._build_ui()
        self._start_sse_listener()
        # Auto-load AWS voices (with flags/icons) on startup if credentials exist
        QTimer.singleShot(300, self._autoload_voices_if_possible)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout()
        central.setLayout(root)

        # Header with title/subtitle and social links
        header = QWidget()
        header_layout = QHBoxLayout()
        # Tighten header spacing/margins to avoid extra gap under title
        try:
            header_layout.setSpacing(0)
            header_layout.setContentsMargins(8, 4, 8, 4)
        except Exception:
            pass
        header.setLayout(header_layout)

        title_box = QVBoxLayout()
        try:
            title_box.setSpacing(0)
            title_box.setContentsMargins(0, 0, 0, 0)
        except Exception:
            pass
        title_label = QLabel('Landing Judge')
        # Improve font smoothing and aesthetics for large title
        try:
            title_label.setObjectName('titleLabel')
            # Reinstate explicit size to respect your change while keeping smoothing
            title_label.setStyleSheet('font-size: 30pt; color: #E6E8EB;')
        except Exception:
            pass
        try:
            f = QFont('Segoe UI')  # High-quality system font on Windows
            f.setPointSize(80)
            f.setBold(True)
            # Prefer antialiasing and quality rendering
            try:
                f.setStyleStrategy(QFont.PreferAntialias)
            except Exception:
                pass
            # Slightly increase letter spacing to reduce harshness at large sizes
            try:
                f.setLetterSpacing(QFont.PercentageSpacing, 102)
            except Exception:
                pass
            title_label.setFont(f)
        except Exception:
            pass
        # Add a subtle soft shadow to make edges feel less sharp
        try:
            from PySide6.QtWidgets import QGraphicsDropShadowEffect
            from PySide6.QtGui import QColor
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(8)
            shadow.setOffset(0, 0)
            shadow.setColor(QColor(0, 0, 0, 150))
            title_label.setGraphicsEffect(shadow)
        except Exception:
            pass
        subtitle_label = QLabel('By CraigyBabyJ 🛬✨')
        try:
            subtitle_label.setContentsMargins(0, 0, 0, 0)
            subtitle_label.setStyleSheet('margin: 0px; padding: 0px;')
        except Exception:
            pass
        try:
            f2 = QFont()
            f2.setPointSize(20)
            subtitle_label.setFont(f2)
        except Exception:
            pass
        title_box.addWidget(title_label)
        title_box.addWidget(subtitle_label)

        # Replace text links with icon buttons
        links_box = QHBoxLayout()
        try:
            links_box.setSpacing(10)
            links_box.setContentsMargins(0, 0, 0, 0)
        except Exception:
            pass
        self._ensure_social_icons()
        self.tiktok_btn = QPushButton()
        self.discord_btn = QPushButton()
        self.website_btn = QPushButton()
        try:
            tiktok_icon_path = Path('static/icons/tiktok.png')
            discord_icon_path = Path('static/icons/discord.png')
            earth_icon_path = Path('static/icons/earth.png')
            if tiktok_icon_path.exists():
                self.tiktok_btn.setIcon(QIcon(str(tiktok_icon_path)))
                self.tiktok_btn.setIconSize(QSize(48, 48))
            else:
                self.tiktok_btn.setText('TikTok')
            if discord_icon_path.exists():
                self.discord_btn.setIcon(QIcon(str(discord_icon_path)))
                self.discord_btn.setIconSize(QSize(48, 48))
            else:
                self.discord_btn.setText('Discord')
            if earth_icon_path.exists():
                self.website_btn.setIcon(QIcon(str(earth_icon_path)))
                self.website_btn.setIconSize(QSize(48, 48))
            else:
                self.website_btn.setText('🌐')
        except Exception:
            self.tiktok_btn.setText('TikTok')
            self.discord_btn.setText('Discord')
            self.website_btn.setText('Website')
        # Make icons blend in: remove button chrome
        for btn in (self.tiktok_btn, self.discord_btn, self.website_btn):
            try:
                btn.setFlat(True)
                btn.setStyleSheet('QPushButton { background: transparent; border: none; padding: 0; }')
                btn.setCursor(Qt.PointingHandCursor)
            except Exception:
                pass
        self.tiktok_btn.setToolTip('Open TikTok')
        self.discord_btn.setToolTip('Open Discord')
        self.website_btn.setToolTip('Open Website')
        try:
            import webbrowser
            self.tiktok_btn.clicked.connect(lambda _=False: webbrowser.open(TIKTOK_URL))
            self.discord_btn.clicked.connect(lambda _=False: webbrowser.open(DISCORD_URL))
            self.website_btn.clicked.connect(lambda _=False: webbrowser.open(WEBSITE_URL))
        except Exception:
            pass
        links_box.addWidget(self.tiktok_btn)
        links_box.addWidget(self.discord_btn)
        links_box.addWidget(self.website_btn)

        header_layout.addLayout(title_box)
        header_layout.addStretch()
        header_layout.addLayout(links_box)

        root.addWidget(header)

        settings_group = QGroupBox('Settings')
        settings_layout = QFormLayout()
        settings_group.setLayout(settings_layout)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(self.default_port)
        try:
            self.port_spin.setToolTip('Port for internal server and overlay. Restart required after change.')
        except Exception:
            pass
        settings_layout.addRow('Port', self.port_spin)
        # Overlay URL label removed per request

        # Banner duration and audio-end grace controls removed per request

        # Region
        self.region_combo = QComboBox()
        regions = [
            'us-east-1','us-east-2','us-west-1','us-west-2',
            'eu-west-1','eu-central-1','ap-south-1','ap-southeast-1','ap-southeast-2',
        ]
        self.region_combo.addItems(regions)
        idx = self.region_combo.findText(self.default_region)
        self.region_combo.setCurrentIndex(max(0, idx))
        try:
            self.region_combo.setToolTip('AWS region used for Amazon Polly Text-to-Speech.')
        except Exception:
            pass
        settings_layout.addRow('AWS Region', self.region_combo)

        # Voice + dynamic loader
        self.voice_combo = QComboBox()
        # Use an emoji-capable font so flag emojis render correctly on Windows
        try:
            self.voice_combo.setFont(QFont("Segoe UI Emoji"))
        except Exception:
            pass
        try:
            self.voice_combo.setToolTip('Select the Amazon Polly voice used for TTS.')
        except Exception:
            pass
        default_voices = [
            'Joanna','Matthew','Amy','Brian','Ivy','Kendra',
            'Kimberly','Salli','Joey','Justin','Emma','Nicole',
        ]
        # Store actual voice id in itemData so we can show rich labels later
        for v in default_voices:
            self.voice_combo.addItem(v, v)
        idx = self.voice_combo.findText(self.default_voice)
        self.voice_combo.setCurrentIndex(max(0, idx))
        self.load_voices_btn = QPushButton('Refresh Voices')
        self.load_voices_btn.setToolTip('Fetch voices and show flags/icons')
        voice_row = QHBoxLayout()
        voice_row.addWidget(self.voice_combo)
        voice_row.addWidget(self.load_voices_btn)
        settings_layout.addRow('Polly Voice', voice_row)

        # Output format
        self.format_combo = QComboBox()
        self.format_combo.addItems(['mp3', 'wav'])
        idx = self.format_combo.findText(self.default_format)
        self.format_combo.setCurrentIndex(max(0, idx))
        settings_layout.addRow('Audio Format', self.format_combo)

        # TTS enable
        self.tts_check = QCheckBox('Enable Text-to-Speech (Polly)')
        self.tts_check.setChecked(self.default_tts)
        try:
            self.tts_check.setToolTip('Enable spoken messages using Amazon Polly.')
        except Exception:
            pass
        # Audio effects
        self.static_noise_check = QCheckBox('Static Only')
        try:
            self.static_noise_check.setToolTip('Play only static noise; mutually exclusive with presets.')
        except Exception:
            pass
        self.static_noise_check.setChecked(self.default_static_noise)
        # Removed redundant Tannoy shortcut; Airport PA preset remains
        # Effect preset checkboxes (mutually exclusive selection)
        try:
            self.default_effect_preset = os.environ.get('EFFECT_PRESET', 'none').strip().lower()
        except Exception:
            self.default_effect_preset = 'none'
        self.preset_checks = {}
        preset_defs = [
            ('None (No Processing)', 'none'),
            ('Airport PA (Terminal/Gate)', 'airport_pa'),
            ('Gate Desk / Jetway', 'gate_desk'),
            ('ATC Radio (Tower/Center)', 'atc_radio'),
            ('Cabin Intercom (Flight deck → pax)', 'cabin_intercom'),
            ('Apron / Outdoor PA', 'apron_outdoor'),
            ('Hangar / Concourse Large', 'hangar_concourse'),
        ]
        preset_container = QWidget()
        # Unified grid: 2 columns x 4 rows; includes static noise + six presets
        preset_layout = QGridLayout()
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setHorizontalSpacing(16)
        preset_layout.setVerticalSpacing(8)
        preset_container.setLayout(preset_layout)
        # Make columns equal width for a clean two-column look
        try:
            preset_layout.setColumnStretch(0, 1)
            preset_layout.setColumnStretch(1, 1)
        except Exception:
            pass
        created_presets = []
        preset_tooltips = {
            'none': 'No processing — clean, direct audio.',
            'airport_pa': 'Simulates terminal/gate PA speaker processing.',
            'gate_desk': 'Simulates gate desk or jetway intercom.',
            'atc_radio': 'Simulates ATC radio (tower/center) with band-limited audio.',
            'cabin_intercom': 'Simulates flight deck to passengers intercom.',
            'apron_outdoor': 'Simulates outdoor apron PA with wind/air bed.',
            'hangar_concourse': 'Simulates large hangar/concourse acoustics.',
        }
        for i, (label, key) in enumerate(preset_defs):
            cb = QCheckBox(label)
            cb.setChecked(key == self.default_effect_preset)
            cb.toggled.connect(lambda checked, k=key: self._on_preset_toggled(k, checked))
            try:
                cb.setToolTip(preset_tooltips.get(key, 'Audio effect preset'))
            except Exception:
                pass
            self.preset_checks[key] = cb
            created_presets.append(cb)
        # Place items into grid: static noise first, then presets
        effects_items = [self.static_noise_check] + created_presets
        for idx, widget in enumerate(effects_items):
            col = 0 if idx < 4 else 1
            row = idx % 4
            try:
                preset_layout.addWidget(widget, row, col, 1, 1, Qt.AlignLeft)
            except Exception:
                preset_layout.addWidget(widget, row, col)
        # Add rows: single 'Audio Effects' row with unified two-column grid
        settings_layout.addRow('Audio Effects', preset_container)
        # Normalize initial selection to ensure exclusivity on first load
        try:
            none_cb = self.preset_checks.get('none')
            if none_cb:
                none_cb.blockSignals(True)
                # If Static Only is enabled, uncheck 'None' preset so only one appears selected
                if self.static_noise_check.isChecked():
                    none_cb.setChecked(False)
                none_cb.blockSignals(False)
            # Sync noise slider state with normalized selection
            try:
                self._update_noise_slider_state()
            except Exception:
                pass
        except Exception:
            pass
        # Unified noise level slider that adapts to current effect
        from PySide6.QtWidgets import QSlider
        self.noise_level_label = QLabel('Noise Level')
        try:
            self.noise_level_label.setToolTip('Adjust noise bed level for the active effect.')
        except Exception:
            pass
        self.noise_level_slider = QSlider(Qt.Horizontal)
        self.noise_level_slider.setRange(0, 100)  # maps to 0.00 – 0.10 gain
        self.noise_level_slider.setSingleStep(1)
        try:
            self.noise_level_slider.setToolTip('Noise level (0–100 maps to 0.00–0.10 gain).')
        except Exception:
            pass
        noise_row = QHBoxLayout()
        noise_row.addWidget(self.noise_level_label)
        noise_row.addWidget(self.noise_level_slider)
        self.noise_container = QWidget()
        self.noise_container.setLayout(noise_row)
        try:
            self.noise_container.setToolTip('Noise controls (disabled if preset has no noise bed).')
        except Exception:
            pass
        settings_layout.addRow('', self.noise_container)
        # Initialize slider visibility and value
        self._update_noise_slider_state()
        # Timing controls removed; no extra-time state to initialize
        # Ensure the checkbox is interactive and updates runtime state
        try:
            self.tts_check.setEnabled(True)
            self.tts_check.setTristate(False)
            self.tts_check.setFocusPolicy(Qt.StrongFocus)
            self.tts_check.toggled.connect(self._on_tts_toggled)
        except Exception:
            pass
        # TTS and Events visibility controls in one row
        self.show_events_check = QCheckBox('Show Events Log')
        self.show_events_check.setChecked(self.default_show_events)
        try:
            self.show_events_check.setToolTip('Show/hide the live events (SSE) log panel.')
        except Exception:
            pass
        try:
            self.show_events_check.toggled.connect(self._on_show_events_toggled)
            self.show_events_check.toggled.connect(self._queue_autosave)
        except Exception:
            pass
        tts_events_row = QHBoxLayout()
        tts_events_row.addWidget(self.tts_check)
        tts_events_row.addWidget(self.show_events_check)
        tts_events_container = QWidget()
        tts_events_container.setLayout(tts_events_row)
        settings_layout.addRow('', tts_events_container)
        # Ding Dong toggle (independent of TTS and cached audio)
        self.dingdong_check = QCheckBox('Play Ding Dong on vote')
        self.dingdong_check.setChecked(getattr(self, 'default_dingdong', False))
        try:
            self.dingdong_check.setToolTip('Play dingdong.mp3 whenever a vote event arrives.')
        except Exception:
            pass
        try:
            self.dingdong_check.setEnabled(True)
            self.dingdong_check.setTristate(False)
            self.dingdong_check.toggled.connect(self._queue_autosave)
        except Exception:
            pass
        settings_layout.addRow('', self.dingdong_check)
        # React to static noise toggle: update slider and runtime var immediately
        try:
            self.static_noise_check.toggled.connect(self._on_static_noise_toggled)
        except Exception:
            pass

        # AWS credentials
        self.key_id = QLineEdit(self.default_key_id)
        try:
            self.key_id.setToolTip('AWS Access Key ID used for Polly TTS.')
        except Exception:
            pass
        self.secret_key = QLineEdit(self.default_secret)
        self.secret_key.setEchoMode(QLineEdit.Password)
        try:
            self.secret_key.setToolTip('AWS Secret Access Key (stored in .env).')
        except Exception:
            pass
        settings_layout.addRow('AWS Access Key ID', self.key_id)
        settings_layout.addRow('AWS Secret Access Key', self.secret_key)

        # Overlay hue is controlled via the "Overlay Colour" button/dialog

        self.save_btn = QPushButton('↩ Reset Defaults')
        self.save_btn.setToolTip('Restore default settings and persist to .env')
        self.open_overlay_btn = QPushButton('🖼 Open Overlay')
        self.open_overlay_btn.setToolTip('Open browser overlay page')
        self.reload_msgs_btn = QPushButton('📝 Edit Quotes')
        self.reload_msgs_btn.setToolTip('Open editor to edit quotes/messages (quotes.json)')
        # Overlay colour controls (moved from overlay to desktop UI)
        self.hue_btn = QPushButton('🎨 Overlay Colour')
        try:
            self.hue_btn.setToolTip('Open overlay colour controls (hue).')
        except Exception:
            pass
        try:
            self.hue_btn.clicked.connect(self.open_hue_dialog)
        except Exception:
            pass
        # Clear sound cache (delete generated audio and index)
        self.clear_cache_btn = QPushButton('🗑 Clear Sound Cache')
        try:
            self.clear_cache_btn.setToolTip('Delete all generated audio files (mp3/wav) and audio_index.json.')
        except Exception:
            pass
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.open_overlay_btn)
        btn_row.addWidget(self.hue_btn)
        btn_row.addWidget(self.reload_msgs_btn)
        btn_row.addWidget(self.clear_cache_btn)
        settings_layout.addRow(btn_row)

        self.status_label = QLabel('')
        self.status_label.setObjectName('statusLabel')
        self.status_label.setWordWrap(True)
        try:
            self.status_label.setToolTip('Status and feedback messages.')
        except Exception:
            pass
        settings_layout.addRow(self.status_label)

        vote_group = QGroupBox('Trigger Votes')
        vote_layout = QGridLayout()
        vote_group.setLayout(vote_layout)
        self.vote_buttons = []
        for i in range(1, 11):
            btn = QPushButton(str(i))
            btn.clicked.connect(lambda _=False, score=i: self.trigger_vote(score))
            try:
                btn.setToolTip(f'Trigger vote score {i}.')
            except Exception:
                pass
            self.vote_buttons.append(btn)
        for idx, btn in enumerate(self.vote_buttons):
            row = idx // 5
            col = idx % 5
            vote_layout.addWidget(btn, row, col)

        self.events_group = QGroupBox('Live Events (SSE)')
        events_layout = QVBoxLayout()
        self.events_group.setLayout(events_layout)
        self.events_view = QTextEdit()
        self.events_view.setReadOnly(True)
        try:
            self.events_view.setToolTip('Live server events and overlay updates.')
        except Exception:
            pass
        events_layout.addWidget(self.events_view)

        root.addWidget(settings_group)
        root.addWidget(vote_group)
        root.addWidget(self.events_group)
        # Apply initial visibility based on env/default
        try:
            self.events_group.setVisible(self.default_show_events)
        except Exception:
            pass

        self.save_btn.clicked.connect(self.reset_defaults)
        self.open_overlay_btn.clicked.connect(self.open_overlay)
        self.load_voices_btn.clicked.connect(self.load_voices_from_aws)
        # Open quotes editor dialog instead of plain reload
        self.reload_msgs_btn.clicked.connect(self.open_quotes_editor)
        # Clear sound cache handler
        self.clear_cache_btn.clicked.connect(self.clear_sound_cache)
        try:
            self.voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        except Exception:
            pass
        # Hue control removed from form; handled via colour dialog

        # Poll SSE queue to update UI
        self.timer = QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self._drain_events)
        self.timer.start()

        # Setup debounced auto-save for settings changes to avoid lag
        try:
            self._setup_autosave()
        except Exception:
            pass

    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port_spin.value()}"

    def _ensure_social_icons(self) -> None:
        try:
            icons_dir = Path('static/icons')
            icons_dir.mkdir(parents=True, exist_ok=True)
            # Use high-quality PNG icons with a soft, circular style
            sources = {
                'tiktok.png': 'https://img.icons8.com/fluency/96/tiktok.png',
                'discord.png': 'https://img.icons8.com/fluency/96/discord-logo.png',
                'earth.png': 'https://img.icons8.com/fluency/96/earth-planet.png',
            }
            for name, url in sources.items():
                dest = icons_dir / name
                try:
                    resp = requests.get(url, timeout=8)
                    if resp.status_code == 200 and resp.content:
                        # Always refresh the icon to ensure latest look
                        dest.write_bytes(resp.content)
                except Exception:
                    pass
        except Exception:
            pass

    def _update_overlay_url_label(self) -> None:
        try:
            # Overlay label removed; nothing to update
            return
        except Exception:
            pass

    def reset_defaults(self):
        """Reset UI controls and environment to opinionated defaults.
        Defaults:
        - Port: 5005
        - Banner duration: 8000 ms
        - AWS region: us-east-1
        - Voice: Joanna
        - Format: mp3
        - TTS: enabled
        - AWS keys: empty
        - Static noise: disabled
        - Effect preset: none
        - Noise levels: static 0.02, radio 0.03, wind 0.03
        """
        try:
            # Set UI widgets
            try:
                self.port_spin.setValue(5005)
            except Exception:
                pass
            try:
                idx = self.region_combo.findText('us-east-1')
                self.region_combo.setCurrentIndex(max(0, idx))
            except Exception:
                pass
            try:
                # Prefer matching by itemData (voice id) if available
                idx = self.voice_combo.findData('Joanna')
                if idx < 0:
                    idx = self.voice_combo.findText('Joanna')
                self.voice_combo.setCurrentIndex(max(0, idx))
            except Exception:
                pass
            try:
                idx = self.format_combo.findText('mp3')
                self.format_combo.setCurrentIndex(max(0, idx))
            except Exception:
                pass
            try:
                self.tts_check.setChecked(True)
            except Exception:
                pass
            try:
                self.dingdong_check.setChecked(False)
            except Exception:
                pass
            try:
                # Hue to neutral by default; update runtime and overlay
                self.current_hue_deg = 0
                self._post_hue_update(0)
            except Exception:
                pass
            try:
                # Show events log by default
                self.show_events_check.blockSignals(True)
                self.show_events_check.setChecked(True)
                self.show_events_check.blockSignals(False)
                self.events_group.setVisible(True)
            except Exception:
                pass
            try:
                self.key_id.setText('')
                self.secret_key.setText('')
            except Exception:
                pass
            try:
                # Clear static noise and presets to 'none'
                self.static_noise_check.blockSignals(True)
                self.static_noise_check.setChecked(False)
                self.static_noise_check.blockSignals(False)
            except Exception:
                pass
            try:
                for k, cb in self.preset_checks.items():
                    cb.blockSignals(True)
                    cb.setChecked(k == 'none')
                    cb.blockSignals(False)
            except Exception:
                pass
            # Reset noise levels and reflect in slider UI
            try:
                self.static_noise_level = 0.02
                self.radio_noise_level = 0.03
                self.wind_noise_level = 0.03
                self._update_noise_slider_state()
            except Exception:
                pass

            # Persist to environment (.env)
            try:
                save_env_var('PORT', '5005')
                save_env_var('AWS_REGION', 'us-east-1')
                save_env_var('POLLY_VOICE_ID', 'Joanna')
                save_env_var('POLLY_OUTPUT_FORMAT', 'mp3')
                save_env_var('ENABLE_TTS', 'true')
                save_env_var('SHOW_EVENTS_LOG', 'true')
                save_env_var('AWS_ACCESS_KEY_ID', '')
                save_env_var('AWS_SECRET_ACCESS_KEY', '')
                save_env_var('ADD_STATIC_NOISE', 'false')
                save_env_var('EFFECT_PRESET', 'none')
                save_env_var('STATIC_NOISE_LEVEL', f"{self.static_noise_level:.3f}")
                save_env_var('RADIO_NOISE_LEVEL', f"{self.radio_noise_level:.3f}")
                save_env_var('WIND_NOISE_LEVEL', f"{self.wind_noise_level:.3f}")
            except Exception:
                pass

            # Update in-memory globals for immediate runtime behavior
            try:
                global PORT, AWS_REGION, POLLY_VOICE_ID, POLLY_OUTPUT_FORMAT, ENABLE_TTS
                global AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, ADD_STATIC_NOISE, EFFECT_PRESET
                global STATIC_NOISE_LEVEL, RADIO_NOISE_LEVEL, WIND_NOISE_LEVEL
                PORT = 5005
                AWS_REGION = 'us-east-1'
                POLLY_VOICE_ID = 'Joanna'
                POLLY_OUTPUT_FORMAT = 'mp3'
                ENABLE_TTS = True
                AWS_ACCESS_KEY_ID = ''
                AWS_SECRET_ACCESS_KEY = ''
                ADD_STATIC_NOISE = False
                EFFECT_PRESET = 'none'
                STATIC_NOISE_LEVEL = float(f"{self.static_noise_level:.3f}")
                RADIO_NOISE_LEVEL = float(f"{self.radio_noise_level:.3f}")
                WIND_NOISE_LEVEL = float(f"{self.wind_noise_level:.3f}")
            except Exception:
                pass

            try:
                self.status_label.setText('Defaults restored. Some changes (like Port) require restart.')
            except Exception:
                pass
        except Exception as e:
            try:
                self.status_label.setText(f'Error resetting defaults: {e}')
            except Exception:
                pass

    def save_settings(self):
        try:
            save_env_var('PORT', str(self.port_spin.value()))
            save_env_var('AWS_REGION', self.region_combo.currentText())
            vid = self.voice_combo.itemData(self.voice_combo.currentIndex()) or self.voice_combo.currentText()
            save_env_var('POLLY_VOICE_ID', vid)
            save_env_var('POLLY_OUTPUT_FORMAT', self.format_combo.currentText())
            save_env_var('ENABLE_TTS', 'true' if self.tts_check.isChecked() else 'false')
            # Persist Ding Dong toggle
            try:
                save_env_var('ENABLE_DINGDONG', 'true' if self.dingdong_check.isChecked() else 'false')
            except Exception:
                pass
            save_env_var('SHOW_EVENTS_LOG', 'true' if self.show_events_check.isChecked() else 'false')
            save_env_var('OVERLAY_HUE_DEG', str(self.current_hue_deg))
            save_env_var('AWS_ACCESS_KEY_ID', self.key_id.text().strip())
            save_env_var('AWS_SECRET_ACCESS_KEY', self.secret_key.text().strip())
            save_env_var('ADD_STATIC_NOISE', 'true' if self.static_noise_check.isChecked() else 'false')
            # Persist per-effect noise levels
            save_env_var('STATIC_NOISE_LEVEL', f"{self.static_noise_level:.3f}")
            save_env_var('RADIO_NOISE_LEVEL', f"{self.radio_noise_level:.3f}")
            save_env_var('WIND_NOISE_LEVEL', f"{self.wind_noise_level:.3f}")
            # Determine selected preset from checkboxes (fall back to 'none' if none checked)
            preset_val = 'none'
            try:
                for key, cb in self.preset_checks.items():
                    if cb.isChecked():
                        preset_val = key
                        break
            except Exception:
                pass
            save_env_var('EFFECT_PRESET', str(preset_val))

            # Apply in-memory immediately for server functions
            global AWS_REGION, POLLY_VOICE_ID, POLLY_OUTPUT_FORMAT, ENABLE_TTS, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
            global ADD_STATIC_NOISE, EFFECT_PRESET
            global STATIC_NOISE_LEVEL, RADIO_NOISE_LEVEL, WIND_NOISE_LEVEL
            AWS_REGION = self.region_combo.currentText()
            POLLY_VOICE_ID = vid
            POLLY_OUTPUT_FORMAT = self.format_combo.currentText()
            ENABLE_TTS = self.tts_check.isChecked()
            global ENABLE_DINGDONG
            ENABLE_DINGDONG = self.dingdong_check.isChecked()
            AWS_ACCESS_KEY_ID = self.key_id.text().strip()
            AWS_SECRET_ACCESS_KEY = self.secret_key.text().strip()
            ADD_STATIC_NOISE = self.static_noise_check.isChecked()
            EFFECT_PRESET = str(preset_val)
            STATIC_NOISE_LEVEL = float(f"{self.static_noise_level:.3f}")
            RADIO_NOISE_LEVEL = float(f"{self.radio_noise_level:.3f}")
            WIND_NOISE_LEVEL = float(f"{self.wind_noise_level:.3f}")

            # Optional quick check: warn if selected voice may not be available in region
            try:
                if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_REGION and POLLY_VOICE_ID:
                    polly = boto3.client(
                        'polly',
                        aws_access_key_id=AWS_ACCESS_KEY_ID,
                        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                        region_name=AWS_REGION,
                    )
                    resp = polly.describe_voices()
                    ids = {v.get('Id') for v in resp.get('Voices', [])}
                    if POLLY_VOICE_ID not in ids:
                        self.status_label.setText(
                            f"Settings saved. Note: '{POLLY_VOICE_ID}' may not be available in {AWS_REGION}."
                        )
                    else:
                        self.status_label.setText('Settings saved and applied. Some changes (like Port) require restart.')
                else:
                    self.status_label.setText('Settings saved and applied. Some changes (like Port) require restart.')
            except Exception:
                self.status_label.setText('Settings saved. Voice availability check skipped due to an error.')
            # Overlay label removed; no immediate update needed
            # Broadcast live audio effects so overlay updates without refresh
            try:
                hub.broadcast({
                    'type': 'settings',
                    'enable_tts': bool(ENABLE_TTS),
                    'enable_dingdong': bool(ENABLE_DINGDONG),
                    'effects': {
                        'static_noise': bool(ADD_STATIC_NOISE),
                        'preset': str(EFFECT_PRESET or 'none'),
                        'static_noise_level': float(STATIC_NOISE_LEVEL or 0.0),
                        'radio_noise_level': float(RADIO_NOISE_LEVEL or 0.0),
                        'wind_noise_level': float(WIND_NOISE_LEVEL or 0.0),
                    },
                })
            except Exception:
                pass
        except Exception as e:
            self.status_label.setText(f'Error saving settings: {e}')

    def _on_preset_toggled(self, key: str, checked: bool) -> None:
        global EFFECT_PRESET
        try:
            if checked:
                # Uncheck all other presets to keep selection exclusive
                for k, cb in self.preset_checks.items():
                    if k != key:
                        cb.blockSignals(True)
                        cb.setChecked(False)
                        cb.blockSignals(False)
                # Apply selection immediately at runtime (without needing Save)
                try:
                    EFFECT_PRESET = str(key)
                    self.status_label.setText(f"Effect preset set to: {key.replace('_',' ').title()}")
                except Exception:
                    pass
                # Ensure Static Only behaves exclusively: turn it off when any preset is selected
                try:
                    self.static_noise_check.blockSignals(True)
                    self.static_noise_check.setChecked(False)
                    self.static_noise_check.blockSignals(False)
                    # Also update runtime var
                    self._on_static_noise_toggled(False)
                except Exception:
                    pass
                # Update noise slider for new selection
                try:
                    self._update_noise_slider_state()
                except Exception:
                    pass
            else:
                # If user unticks the selected one, leave none selected
                try:
                    if EFFECT_PRESET == key:
                        EFFECT_PRESET = 'none'
                        self.status_label.setText("Effect preset cleared (none)")
                except Exception:
                    pass
                try:
                    self._update_noise_slider_state()
                except Exception:
                    pass

        except Exception:
            pass


    def _on_show_events_toggled(self, enabled: bool) -> None:
        try:
            # Toggle visibility and persist immediately
            try:
                self.events_group.setVisible(bool(enabled))
            except Exception:
                pass
            save_env_var('SHOW_EVENTS_LOG', 'true' if enabled else 'false')
            try:
                self.status_label.setText('Events log shown.' if enabled else 'Events log hidden.')
            except Exception:
                pass
        except Exception:
            try:
                self.status_label.setText('Failed to toggle events log visibility.')
            except Exception:
                pass

    def _on_static_noise_toggled(self, enabled: bool) -> None:
        try:
            # Update runtime and UI state immediately
            global ADD_STATIC_NOISE
            ADD_STATIC_NOISE = bool(enabled)
            if enabled:
                # Make Static Only act like an exclusive effect selection
                # Uncheck all other presets and set preset to 'none'
                try:
                    for k, cb in self.preset_checks.items():
                        cb.blockSignals(True)
                        cb.setChecked(False)
                        cb.blockSignals(False)
                except Exception:
                    pass
                try:
                    global EFFECT_PRESET
                    EFFECT_PRESET = 'none'
                except Exception:
                    pass
                self.status_label.setText('Static Only enabled (no processing preset active)')
            else:
                self.status_label.setText('Static Only disabled')
            self._update_noise_slider_state()
            # Autosave env var for static toggle with debounce
            try:
                self._queue_autosave()
            except Exception:
                pass
            # Broadcast live effects change immediately
            try:
                hub.broadcast({
                    'type': 'settings',
                    'enable_tts': bool(ENABLE_TTS),
                    'effects': {
                        'static_noise': bool(ADD_STATIC_NOISE),
                        'preset': str(EFFECT_PRESET or 'none'),
                        'static_noise_level': float(STATIC_NOISE_LEVEL or 0.0),
                        'radio_noise_level': float(RADIO_NOISE_LEVEL or 0.0),
                        'wind_noise_level': float(WIND_NOISE_LEVEL or 0.0),
                    },
                })
            except Exception:
                pass
        except Exception:
            pass

    # -------------------- Auto-save (Debounced) --------------------
    def _setup_autosave(self) -> None:
        # Single-shot timer to batch rapid changes
        from PySide6.QtCore import QTimer as _QTimer
        self._autosave_timer = _QTimer(self)
        self._autosave_timer.setInterval(750)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._autosave_settings)

        # Wire settings inputs to queue an autosave
        try:
            self.port_spin.valueChanged.connect(self._queue_autosave)
            self.region_combo.currentIndexChanged.connect(self._queue_autosave)
            self.voice_combo.currentIndexChanged.connect(self._queue_autosave)
            self.format_combo.currentIndexChanged.connect(self._queue_autosave)
            self.tts_check.toggled.connect(self._queue_autosave)
            self.dingdong_check.toggled.connect(self._queue_autosave)
            # Credentials: save when editing finishes to avoid writes every keystroke
            self.key_id.editingFinished.connect(self._queue_autosave)
            self.secret_key.editingFinished.connect(self._queue_autosave)
            # Also autosave on text changes with debounce, so focus loss is not required
            self.key_id.textChanged.connect(self._queue_autosave)
            self.secret_key.textChanged.connect(self._queue_autosave)
            # Effect preset changes also autosave
            for cb in self.preset_checks.values():
                cb.toggled.connect(self._queue_autosave)
            # Static noise checkbox autosave is handled in _on_static_noise_toggled too
        except Exception:
            pass

    def _queue_autosave(self) -> None:
        try:
            # Restart debounce window
            self._autosave_timer.stop()
            self._autosave_timer.start()
        except Exception:
            pass

    def _autosave_settings(self) -> None:
        # Persist key settings to .env without heavy UI spam
        try:
            save_env_var('PORT', str(self.port_spin.value()))
            save_env_var('AWS_REGION', self.region_combo.currentText())
            # Voice, format, TTS
            try:
                vid = self.voice_combo.currentText()
                if vid:
                    save_env_var('POLLY_VOICE_ID', vid)
            except Exception:
                pass
            try:
                save_env_var('POLLY_OUTPUT_FORMAT', self.format_combo.currentText())
            except Exception:
                pass
            save_env_var('ENABLE_TTS', 'true' if self.tts_check.isChecked() else 'false')
            try:
                save_env_var('ENABLE_DINGDONG', 'true' if self.dingdong_check.isChecked() else 'false')
            except Exception:
                pass
            try:
                save_env_var('SHOW_EVENTS_LOG', 'true' if self.show_events_check.isChecked() else 'false')
            except Exception:
                pass
            try:
                save_env_var('OVERLAY_HUE_DEG', str(self.current_hue_deg))
            except Exception:
                pass
            # Credentials: capture current values when editing finished fired
            save_env_var('AWS_ACCESS_KEY_ID', self.key_id.text().strip())
            save_env_var('AWS_SECRET_ACCESS_KEY', self.secret_key.text().strip())
            # Effect preset and static toggle
            try:
                preset_val = EFFECT_PRESET if EFFECT_PRESET else 'none'
                save_env_var('EFFECT_PRESET', str(preset_val))
            except Exception:
                pass
            save_env_var('ADD_STATIC_NOISE', 'true' if self.static_noise_check.isChecked() else 'false')
            # Update in-memory config so votes and overlay use latest values
            try:
                # No timing settings to update in memory anymore
                pass
            except Exception:
                pass

            # Broadcast live settings so overlay updates without refresh
            try:
                hub.broadcast({
                    'type': 'settings',
                    'enable_tts': bool(ENABLE_TTS),
                    'enable_dingdong': bool(self.dingdong_check.isChecked()),
                    'effects': {
                        'static_noise': bool(ADD_STATIC_NOISE),
                        'preset': str(EFFECT_PRESET or 'none'),
                        'static_noise_level': float(STATIC_NOISE_LEVEL or 0.0),
                        'radio_noise_level': float(RADIO_NOISE_LEVEL or 0.0),
                        'wind_noise_level': float(WIND_NOISE_LEVEL or 0.0),
                    },
                })
            except Exception:
                pass

            # Show concise confirmation
            try:
                self.status_label.setText('Settings auto-saved.')
            except Exception:
                pass
        except Exception:
            try:
                self.status_label.setText('Auto-save failed.')
            except Exception:
                pass

    # Extra time controls removed; no handlers required

    def _on_hue_changed(self, deg: int) -> None:
        try:
            # Persist and broadcast theme change
            save_env_var('OVERLAY_HUE_DEG', str(int(deg)))
            try:
                hub.broadcast({'type': 'theme', 'hue_deg': int(deg)})
            except Exception:
                pass
            try:
                self.status_label.setText(f'Overlay hue set to {int(deg)}°')
            except Exception:
                pass
        except Exception:
            try:
                self.status_label.setText('Failed to update overlay hue.')
            except Exception:
                pass

    def _active_noise_kind(self) -> str:
        try:
            # Determine current selected preset
            active_preset = 'none'
            for key, cb in self.preset_checks.items():
                if cb.isChecked():
                    active_preset = key
                    break
            if active_preset == 'atc_radio':
                return 'radio'
            if active_preset == 'apron_outdoor':
                return 'wind'
            # With no noise-capable preset, allow Static Only slider when enabled
            if active_preset == 'none' and self.static_noise_check.isChecked():
                return 'static'
            return ''
        except Exception:
            return ''

    def _level_to_slider(self, level: float) -> int:
        try:
            # Map 0.00–0.10 -> 0–100
            v = int(round(max(0.0, min(0.10, float(level))) * 1000))
            return max(0, min(100, v))
        except Exception:
            return 0

    def _slider_to_level(self, value: int) -> float:
        try:
            # Map 0–100 -> 0.00–0.10
            v = max(0, min(100, int(value)))
            return round(v / 1000.0, 3)
        except Exception:
            return 0.0

    def _update_noise_slider_state(self) -> None:
        try:
            kind = self._active_noise_kind()
            has_kind = bool(kind)
            # Keep the row visible to avoid UI resizing; disable when inactive
            self.noise_container.setVisible(True)
            self.noise_level_slider.setEnabled(has_kind)
            if not has_kind:
                # Reserve space with a neutral label and no-op slider
                self.noise_level_label.setText('Noise Level (inactive for this preset)')
                self.noise_level_slider.setValue(self._level_to_slider(0.0))
                try:
                    self.noise_level_slider.valueChanged.disconnect()
                except Exception:
                    pass
                return
            if kind == 'radio':
                self.noise_level_label.setText('Radio Hiss Level')
                self.noise_level_slider.setValue(self._level_to_slider(self.radio_noise_level))
            elif kind == 'wind':
                self.noise_level_label.setText('Wind/Air Bed Level')
                self.noise_level_slider.setValue(self._level_to_slider(self.wind_noise_level))
            else:
                self.noise_level_label.setText('Static Noise Level')
                self.noise_level_slider.setValue(self._level_to_slider(self.static_noise_level))
            # Connect once
            try:
                self.noise_level_slider.valueChanged.disconnect()
            except Exception:
                pass
            self.noise_level_slider.valueChanged.connect(self._on_noise_level_changed)
        except Exception:
            pass

    def _on_noise_level_changed(self, value: int) -> None:
        try:
            level = self._slider_to_level(value)
            kind = self._active_noise_kind()
            if kind == 'radio':
                self.radio_noise_level = level
                try:
                    global RADIO_NOISE_LEVEL
                    RADIO_NOISE_LEVEL = float(f"{self.radio_noise_level:.3f}")
                except Exception:
                    pass
                self.status_label.setText(f"Radio hiss level set to {level:.3f}")
            elif kind == 'wind':
                self.wind_noise_level = level
                try:
                    global WIND_NOISE_LEVEL
                    WIND_NOISE_LEVEL = float(f"{self.wind_noise_level:.3f}")
                except Exception:
                    pass
                self.status_label.setText(f"Wind/air bed level set to {level:.3f}")
            else:
                self.static_noise_level = level
                try:
                    global STATIC_NOISE_LEVEL
                    STATIC_NOISE_LEVEL = float(f"{self.static_noise_level:.3f}")
                except Exception:
                    pass
                self.status_label.setText(f"Static noise level set to {level:.3f}")
            # Broadcast updated levels immediately so overlay reflects slider changes
            try:
                global ENABLE_TTS, ADD_STATIC_NOISE, EFFECT_PRESET
                hub.broadcast({
                    'type': 'settings',
                    'enable_tts': bool(ENABLE_TTS),
                    'effects': {
                        'static_noise': bool(ADD_STATIC_NOISE),
                        'preset': str(EFFECT_PRESET or 'none'),
                        'static_noise_level': float(STATIC_NOISE_LEVEL or 0.0),
                        'radio_noise_level': float(RADIO_NOISE_LEVEL or 0.0),
                        'wind_noise_level': float(WIND_NOISE_LEVEL or 0.0),
                    },
                })
            except Exception:
                pass
            # Debounced autosave to persist level changes without manual save
            try:
                self._queue_autosave()
            except Exception:
                pass
        except Exception:
            pass

    def _post_hue_update(self, deg: int):
        try:
            url = f"{self.base_url()}/theme"
            requests.post(url, json={"hue_deg": int(deg)})
            # Track current hue locally
            try:
                self.current_hue_deg = int(deg)
            except Exception:
                pass
            self.status_label.setText(f"Overlay hue updated: {int(deg)}°")
        except Exception:
            # Non-fatal; still update UI state
            self.status_label.setText('Failed to update overlay hue')

    def open_hue_dialog(self):
        dlg = QDialog(self)
        try:
            dlg.setWindowTitle('Overlay Colour')
        except Exception:
            pass
        layout = QVBoxLayout()
        try:
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(8)
        except Exception:
            pass
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 360)
        try:
            slider.setSingleStep(5)
        except Exception:
            pass
        try:
            current_deg = int(self.current_hue_deg)
        except Exception:
            try:
                current_deg = int(self.default_hue)
            except Exception:
                current_deg = 0
        slider.setValue(current_deg)
        value_label = QLabel(f'Hue: {current_deg}°')
        btns = QHBoxLayout()
        reset_btn = QPushButton('Reset')
        close_btn = QPushButton('Close')
        btns.addWidget(reset_btn)
        btns.addWidget(close_btn)
        layout.addWidget(value_label)
        layout.addWidget(slider)
        layout.addLayout(btns)
        dlg.setLayout(layout)
        try:
            slider.valueChanged.connect(lambda v: (value_label.setText(f'Hue: {int(v)}°'), self._post_hue_update(int(v))))
            reset_btn.clicked.connect(lambda: (slider.setValue(0), self._post_hue_update(0)))
            close_btn.clicked.connect(dlg.accept)
        except Exception:
            pass
        # Show the dialog and toggle preview so the overlay is visible while adjusting
        try:
            self._post_preview(True, 1)
            dlg.exec()
        except Exception:
            pass
        finally:
            # Turn preview off when dialog closes
            try:
                self._post_preview(False, 1)
            except Exception:
                pass

    def _default_quotes_payload(self) -> dict:
        """Return the default quotes payload from backup file."""
        default_file = os.path.join(os.path.dirname(__file__), 'quotes.default.json')
        try:
            with open(default_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            # Fallback if default file doesn't exist
            return {
                "quotes": {
                    "1": [
                        "Well, that was... educational.",
                        "Physics called—they want an explanation."
                    ],
                    "2": ["Hard arrival. Teeth still rattling."],
                    "3": ["Firm. The landing gear filed a complaint."],
                    "4": ["Not bad, not smooth. We felt it."],
                    "5": ["Acceptable. Coffee only trembled."],
                    "6": ["Decent touch. Cabin crew kept pouring."],
                    "7": ["Nice! Most passengers missed it."],
                    "8": ["Smooth operator. Butter adjacent."],
                    "9": ["Greased it. Polite applause engaged."],
                    "10": [
                        "Absolute butter.",
                        "Chief pilot approved!"
                    ]
                },
                "messages": {
                    "1": "Mayday? That was… educational.",
                    "2": "Hard arrival. Teeth still rattling.",
                    "3": "Firm. The landing gear filed a complaint.",
                    "4": "Not bad, not smooth. We felt it.",
                    "5": "Acceptable. Coffee only trembled.",
                    "6": "Decent touch. Cabin crew kept pouring.",
                    "7": "Nice! Most passengers missed it.",
                    "8": "Smooth operator. Butter adjacent.",
                    "9": "Greased it. Polite applause engaged.",
                    "10": "Absolute butter. Chief pilot approved!"
                }
            }

    def _save_quotes_and_reload(self, raw_text: str) -> None:
        """Validate JSON, persist to quotes.json, and reload in-memory messages."""
        try:
            payload = json.loads(raw_text)
            if not isinstance(payload, dict):
                raise ValueError("Top-level JSON must be an object")
            # Ensure keys exist
            if "quotes" not in payload:
                payload["quotes"] = self._default_quotes_payload()["quotes"]
            if "messages" not in payload:
                payload["messages"] = self._default_quotes_payload()["messages"]
            # Persist
            QUOTES_FILE.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            # Refresh in-memory messages used for API responses
            self.reload_messages()
            try:
                self.status_label.setText("Quotes saved and reloaded from quotes.json.")
            except Exception:
                pass
        except Exception as e:
            try:
                self.status_label.setText(f"Error saving quotes: {e}")
            except Exception:
                pass

    def open_quotes_editor(self) -> None:
        """Open a simple in-app editor for quotes.json with save/reset controls."""
        dlg = QDialog(self)
        try:
            dlg.setWindowTitle("Edit Quotes (quotes.json)")
        except Exception:
            pass
        layout = QVBoxLayout()
        try:
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(8)
        except Exception:
            pass

        info = QLabel(
            "Edit the JSON for quotes/messages. Click ‘Save & Reload’ to apply, or ‘Reset to Defaults’."
        )
        editor = QTextEdit()
        # Load current file or minimal defaults
        try:
            txt = QUOTES_FILE.read_text(encoding="utf-8")
        except Exception:
            txt = json.dumps(self._default_quotes_payload(), indent=2, ensure_ascii=False)
        editor.setText(txt)

        btns = QHBoxLayout()
        save_btn = QPushButton("Save & Reload")
        reset_btn = QPushButton("Reset to Defaults")
        close_btn = QPushButton("Close")
        btns.addWidget(save_btn)
        btns.addWidget(reset_btn)
        btns.addWidget(close_btn)

        layout.addWidget(info)
        layout.addWidget(editor)
        layout.addLayout(btns)
        dlg.setLayout(layout)

        try:
            save_btn.clicked.connect(lambda: self._save_quotes_and_reload(editor.toPlainText()))
            reset_btn.clicked.connect(lambda: (editor.setText(json.dumps(self._default_quotes_payload(), indent=2, ensure_ascii=False)), self._save_quotes_and_reload(editor.toPlainText())))
            close_btn.clicked.connect(dlg.accept)
        except Exception:
            pass

        try:
            dlg.resize(700, 600)
            dlg.exec()
        except Exception:
            pass

    def open_overlay(self):
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(f"{self.base_url()}/overlay"))
        except Exception:
            import webbrowser
            webbrowser.open(f"{self.base_url()}/overlay")

    def clear_sound_cache(self) -> None:
        """Confirm and delete all generated audio files and the audio index.

        Removes *.mp3 and *.wav under static/audio, and deletes static/audio/audio_index.json.
        The index will be recreated automatically the next time an audio clip is generated.
        """
        try:
            msg = (
                "You are about to delete all stored audio files (MP3/WAV) in static/audio "
                "and remove audio_index.json.\n\nThis cannot be undone.\n\nProceed?"
            )
            result = QMessageBox.question(
                self,
                "Clear Sound Cache",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if result != QMessageBox.StandardButton.Yes:
                try:
                    self.status_label.setText('Clear Sound Cache canceled.')
                except Exception:
                    pass
                return

            deleted = 0
            errors = []
            audio_dir = Path(app.static_folder) / 'audio'
            try:
                if audio_dir.exists():
                    for pattern in ('*.mp3', '*.wav'):
                        for p in audio_dir.glob(pattern):
                            try:
                                p.unlink()
                                deleted += 1
                            except Exception as e:
                                errors.append(f"Failed to delete {p.name}: {e}")
            except Exception as e:
                errors.append(f"Audio folder error: {e}")

            # Delete the audio index file
            try:
                if AUDIO_INDEX_PATH.exists():
                    AUDIO_INDEX_PATH.unlink()
            except Exception as e:
                errors.append(f"Failed to delete audio_index.json: {e}")

            if errors:
                self.status_label.setText(
                    f"Cleared {deleted} audio files. Some items failed: " + "; ".join(errors)
                )
            else:
                self.status_label.setText(
                    f"Cleared {deleted} audio files and removed audio_index.json. "
                    "No restart needed; index will recreate on next audio generation."
                )
        except Exception as e:
            try:
                self.status_label.setText(f"Error clearing sound cache: {e}")
            except Exception:
                pass

    def trigger_vote(self, score: int):
        url = f"{self.base_url()}/vote/{score}"
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                self.status_label.setText(f"Sent vote {score}. Overlay should update.")
            else:
                self.status_label.setText(f"Vote failed ({resp.status_code}). Is server running?")
        except Exception as e:
            self.status_label.setText(f"Vote error: {e}")

    def _post_preview(self, active: bool, score: int = 1) -> None:
        try:
            url = f"{self.base_url()}/preview"
            payload = {'active': bool(active), 'score': int(score)}
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass

    def load_voices_from_aws(self):
        key_id = self.key_id.text().strip()
        secret = self.secret_key.text().strip()
        region = self.region_combo.currentText().strip()
        if not key_id or not secret:
            self.status_label.setText('Enter AWS credentials to load voices.')
            return
        try:
            polly = boto3.client(
                'polly',
                aws_access_key_id=key_id,
                aws_secret_access_key=secret,
                region_name=region,
            )
            catalog = list_region_voices(polly)
            if not catalog:
                self.status_label.setText('No voices returned. Check region or credentials.')
                return
            # De-duplicate by Id and capture supported engines
            by_id = {}
            for v in catalog:
                vid = v.get('Id')
                if not vid:
                    continue
                by_id[vid] = (
                    v.get('LanguageName', ''),
                    v.get('LanguageCode', ''),
                    v.get('SupportedEngines', []),
                )
            self.voice_combo.clear()
            items = []
            for vid in by_id.keys():
                lname, lcode, engines = by_id[vid]
                items.append((voice_priority(lcode), vid, lname, lcode, engines))
            for _, vid, lname, lcode, engines in sorted(items, key=lambda t: (t[0], t[1])):
                base_label = voice_label(vid, lname, lcode)
                label = f"{base_label} • Natural" if ('neural' in engines) else base_label
                icon = flag_icon_for_lang(lcode)
                if icon.isNull():
                    self.voice_combo.addItem(label, vid)
                    idx_added = self.voice_combo.count() - 1
                else:
                    self.voice_combo.addItem(icon, label, vid)
                    idx_added = self.voice_combo.count() - 1
                # Add tooltip showing language and supported engines
                try:
                    eng_text = ", ".join(engines) if engines else "standard"
                    tooltip = f"{lname} [{lcode}] • Engines: {eng_text}"
                    self.voice_combo.setItemData(idx_added, tooltip, Qt.ItemDataRole.ToolTipRole)
                except Exception:
                    pass
            # Select default voice id if present
            idx = self.voice_combo.findData(self.default_voice)
            if idx < 0:
                idx = self.voice_combo.findText(self.default_voice)
            self.voice_combo.setCurrentIndex(max(0, idx))
            self.status_label.setText(f'Loaded {len(by_id)} voices from AWS Polly. “Natural” indicates neural support.')
        except Exception as e:
            self.status_label.setText(f'Error loading voices: {e}')

    def _on_tts_toggled(self, enabled: bool):
        try:
            global ENABLE_TTS
            ENABLE_TTS = bool(enabled)
            self.status_label.setText('Text-to-Speech enabled' if enabled else 'Text-to-Speech disabled')
            # Immediately persist the change to .env
            try:
                save_env_var('ENABLE_TTS', 'true' if enabled else 'false')
                print(f"[DEBUG] TTS toggled to: {enabled}, saved to .env")
            except Exception as e:
                print(f"[DEBUG] Failed to save TTS to .env: {e}")
            # Small delay to ensure .env is written before any votes might be triggered
            import time
            time.sleep(0.1)
            # Inform overlay immediately so it can stop any playing audio
            try:
                hub.broadcast({'type': 'settings', 'enable_tts': bool(ENABLE_TTS)})
                print(f"[DEBUG] TTS settings broadcast sent: {ENABLE_TTS}")
            except Exception as e:
                print(f"[DEBUG] Failed to broadcast TTS settings: {e}")
            # Also queue autosave for any other pending changes
            try:
                self._queue_autosave()
            except Exception:
                pass
        except Exception as e:
            print(f"[DEBUG] Error in TTS toggle handler: {e}")

    def _on_voice_changed(self, idx: int):
        try:
            vid = self.voice_combo.itemData(idx)
            if not isinstance(vid, str) or not vid:
                vid = self.voice_combo.itemText(idx)
            global POLLY_VOICE_ID
            POLLY_VOICE_ID = vid
            self.status_label.setText(f"Voice set to {vid}. Click Save to persist.")
        except Exception:
            pass

    def reload_messages(self):
        try:
            global MESSAGES
            MESSAGES = load_messages()
            self.status_label.setText('Messages reloaded from quotes.json.')
        except Exception as e:
            self.status_label.setText(f'Error reloading messages: {e}')

    def _start_sse_listener(self):
        def listen():
            # Wait briefly for server to start
            time.sleep(0.8)
            url = f"{self.base_url()}/stream"
            while True:
                try:
                    with requests.get(url, stream=True, timeout=60) as r:
                        buff = ''
                        for raw in r.iter_lines(decode_unicode=True):
                            if raw is None:
                                continue
                            line = raw.strip()
                            if line.startswith('data:'):
                                try:
                                    payload = json.loads(line[5:].strip())
                                    self.events_queue.put(payload)
                                except Exception:
                                    pass
                except Exception:
                    time.sleep(1.0)

        th = threading.Thread(target=listen, daemon=True)
        th.start()

    def _autoload_voices_if_possible(self):
        """On first launch, replace the basic default list with the flagged list
        by calling AWS describe_voices if credentials are available. Uses a
        simple heuristic to avoid reloading when already populated with labels/icons.
        """
        try:
            key_id = self.key_id.text().strip()
            secret = self.secret_key.text().strip()
            region = self.region_combo.currentText().strip()
            if not (key_id and secret and region):
                return
            # If the first item label equals its data, it's likely the plain default list
            if self.voice_combo.count() > 0:
                first_label = self.voice_combo.itemText(0)
                first_data = self.voice_combo.itemData(0)
                if isinstance(first_data, str) and first_label == first_data:
                    self.load_voices_from_aws()
        except Exception:
            # Non-fatal: leave default list if anything goes wrong
            pass

    def _drain_events(self):
        drained = []
        while True:
            try:
                drained.append(self.events_queue.get_nowait())
            except Exception:
                break
        for p in drained:
            try:
                if p.get('type') == 'vote':
                    msg = (
                        f"[{p.get('ts','')}] score={p.get('score')} level={p.get('level')} "
                        f"msg={p.get('message','')} quote={p.get('quote','')}"
                    )
                else:
                    msg = json.dumps(p)
                self.events_view.append(msg)
            except Exception:
                pass


def main():
    # Allow an opt-in console for windowed builds when requested
    _enable_debug_console_if_requested()
    # Configure HiDPI and pixmap smoothing before creating the QApplication instance
    try:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    except Exception:
        pass
    # Start Flask server in background
    server_thread = threading.Thread(target=start_server, args=(PORT,), daemon=True)
    server_thread.start()

    # Start UI
    app_qt = QApplication(sys.argv)
    # Set a global application icon early so Windows taskbar uses it
    try:
        # Prefer the bundled static path; fallback to source path for dev
        icon_path = Path(app.static_folder) / 'icons' / 'icon.png'
        if not icon_path.exists():
            # PyInstaller onedir layout often places data under _internal
            try:
                exe_dir = Path(getattr(sys, 'frozen', False) and os.path.dirname(sys.executable) or os.getcwd())
                alt_path = exe_dir / '_internal' / 'static' / 'icons' / 'icon.png'
                if alt_path.exists():
                    icon_path = alt_path
            except Exception:
                pass
        if not icon_path.exists():
            icon_path = Path('static/icons/icon.png')
        if icon_path.exists():
            app_qt.setWindowIcon(QIcon(str(icon_path)))
    except Exception:
        pass
    # Emoji-capable font for nicer icons/labels
    try:
        app_qt.setFont(QFont('Segoe UI Emoji', 10))
    except Exception:
        pass
    # Apply modern theme
    try:
        app_qt.setStyleSheet(ui_stylesheet())
    except Exception:
        pass
    win = AllInOneUI()
    win.resize(800, 600)
    # Force window to appear prominently
    try:
        win.raise_()
        win.activateWindow()
        win.setWindowState(win.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
    except Exception:
        pass
    win.show()
    sys.exit(app_qt.exec())


if __name__ == '__main__':
    main()