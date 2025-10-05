# Landing Judge

An opinionated, local overlay and control app for rating landings from 1–10 with a snappy on‑screen banner, a witty quote, and optional text‑to‑speech audio. Designed for streamers and coaches who want quick, punchy feedback in OBS or any broadcasting setup.

## Features
- Animated overlay banner with tiered colors and subtle motion.
- Witty quote per score, plus optional Amazon Polly TTS playback.
- Fixed, client‑side banner visibility (defaults to 1500 ms) for predictable pacing.
- One‑click Desktop UI for settings and testing votes.
- Stream Deck integration for 10 fast vote buttons.
- Simple API (`GET /vote/<score>`) for external triggers.
- Editable quotes (`quotes.json`) with a safe default backup (`quotes.default.json`).

## Quick Start
1. Install Python 3.10+.
2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
3. Run the server:
   ```powershell
   python all_in_one.py
   ```
4. Open the overlay in a browser or OBS Browser Source:
   - URL: `http://127.0.0.1:5005/overlay`
5. Trigger a test vote (1–10):
   ```powershell
   curl "http://127.0.0.1:5005/vote/8"
   ```

Pro tip: The overlay is transparent until a vote or preview is triggered.

## Publish to GitHub
Make the repo public and push it to GitHub as `landing-judge`.

1. Create a new public repo on GitHub named `landing-judge`.
2. In the project folder, initialize and commit locally:
   ```powershell
   git init
   git add .
   git commit -m "Public release: Landing Judge"
   ```
3. Add the remote and push:
   ```powershell
   git branch -M main
   git remote add origin https://github.com/<your-username>/landing-judge.git
   git push -u origin main
   ```
4. Update your Stream Deck profile and OBS scene names to match “Landing Judge” if desired.

## Desktop UI
The optional control panel lets you edit `.env` settings, open the overlay, and trigger votes.

Run it:
```powershell
python ui.py
```

What you can adjust:
- `Port`: Overlay/API server port.
- `AWS Region`, `Voice`, `Format`: Amazon Polly TTS options.
- `Enable TTS`: Toggle audio generation/playback for quotes.
- `Show Events Log`: Show/hide live event stream in the UI.
- `Audio Effects` and `Noise`: Choose a preset and dial in static/radio/wind levels.

Buttons 1–10 trigger `GET /vote/<score>` so you can test without Stream Deck.

## Stream Deck Setup
You have two easy options. The built‑in “Website” action works out of the box; an HTTP plugin avoids opening a browser.

Option A — Built‑in Website action (simple):
1. Open Stream Deck and create or select a profile for your stream.
2. Drag “Website” onto a blank button.
3. Set “URL” to `http://127.0.0.1:5005/vote/1` and title the button `1`.
4. Duplicate the button and update the URL to `/vote/2`, `/vote/3`, … up to `/vote/10`.
5. Keep `all_in_one.py` running while streaming.

Note: The Website action may open a browser tab on press. If you prefer a silent request, use Option B.

Option B — HTTP GET plugin (silent requests):
1. Install a lightweight HTTP request plugin (e.g., “BarRaider’s HTTP Request”).
2. Drag the HTTP action onto a button.
3. Set Method to `GET` and URL to `http://127.0.0.1:5005/vote/1`.
4. Title the button `1` and repeat for scores `2`–`10`.
5. Ensure Landing Judge is running so the overlay receives the votes.

Tips:
- Place buttons 1–10 in a single row for muscle memory.
- Use icons/colors to match tiers (bad/ok/good/great) if you like.
- Test with the Desktop UI first to confirm overlay and audio behave as expected.

## Screenshots
Add images to `static/screenshots/` and they’ll render in this section.

- Overlay in OBS
  ![Overlay in OBS](static/screenshots/obs-overlay.png)

- Desktop UI Control Panel
  ![Desktop UI](static/screenshots/ui-panel.png)

To capture:
- OBS: Right-click the Browser Source preview → `Screenshot Output` or use Windows `Win+Shift+S`.
- Desktop UI: Press `Alt+Print Screen` or use `Win+Shift+S`, then save to `static/screenshots/`.

## Overlay in OBS
- Add a Browser Source with URL `http://127.0.0.1:5005/overlay`.
- Set size to your canvas (e.g., 1920×1080). The overlay is transparent when idle.
- Enable “Refresh browser when scene becomes active” if you switch scenes often.
- If you want overlay audio, ensure your Browser Source audio is monitored/mixed in OBS.

Timing: The overlay uses a fixed client‑side display time of 1500 ms. Server timing fields are currently ignored by the overlay.

## API Example
```bash
curl "http://127.0.0.1:5005/vote/8"
```
Sample response (overlay consumes `quote`, `audio_url`, `score`, `level`; timing fields are ignored by the overlay):
```json
{
  "type": "vote",
  "score": 8,
  "message": "Smooth operator. Butter adjacent.",
  "quote": "That was the sweet spot of aviation sass.",
  "audio_url": "/static/quote_abc123.mp3",
  "level": "good",
  "duration_ms": 8000,
  "ts": "2025-09-30T16:48:09Z"
}
```

## Configuration (.env)
Common environment variables (managed by the Desktop UI):
- `PORT`: HTTP server and overlay port (default `5005`).
- `ENABLE_TTS`: `true|false` to enable Text‑to‑Speech for quotes.
- `AWS_REGION`: Amazon Polly region, e.g., `us-east-1`.
- `POLLY_VOICE_ID`: Polly voice, e.g., `Joanna`.
- `POLLY_OUTPUT_FORMAT`: Audio format, e.g., `mp3`.
- `ADD_STATIC_NOISE`: Add static noise bed (`true|false`).
- `EFFECT_PRESET`: Audio processing preset name (`none`, `tower_radio`, `apron_outdoor`, etc.).
- `STATIC_NOISE_LEVEL`, `RADIO_NOISE_LEVEL`, `WIND_NOISE_LEVEL`: Per‑effect levels.

Timing controls such as `BANNER_DURATION_MS`, `BANNER_MIN_LINGER_MS`, and `HIDE_ON_AUDIO_END` exist server‑side but are currently ignored by the client overlay, which uses a fixed internal duration (1500 ms).

## Quotes and Messages
- `quotes.json` holds two sections: `quotes` (arrays by score 1–10) and `messages` (one‑liners by score).
- The overlay displays the selected `quote` string and plays `audio_url` if available.
- The `messages` map is included in the API response and useful for logs or external consumers, but is not rendered on the overlay.
- Resetting to defaults uses `quotes.default.json` (a full backup of the original set). If it’s missing, a minimal fallback is used.

Editing quotes:
1. Stop the server.
2. Edit `quotes.json` (keep both `quotes` and `messages` present).
3. Start the server and test votes.

## Troubleshooting
- Overlay not showing: Confirm the URL, port, and that a vote/preview has been triggered.
- No audio: Ensure TTS is enabled, AWS credentials are set, and OBS browser audio is routed.
- Stream Deck buttons do nothing: Verify the server is running and URLs are `http://127.0.0.1:5005/vote/<1..10>`.
- Quotes missing: Restore `quotes.default.json` and use the reset function, or copy its contents back to `quotes.json`.

## License
This project is provided as‑is for personal streaming and coaching use.