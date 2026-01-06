# Landing Judge

A playful, local overlay and control app for rating landings from 1–10 — complete with a snappy on‑screen banner, witty quotes, and optional text‑to‑speech. Perfect for group flying nights, VA events, VATSIM/IVAO meet‑ups, or casual squad sessions where you rate each other’s landings and keep the banter flowing.

Use it to crown the “butter king,” call out the “firm” arrivals, and add a bit of personality to your stream or Discord. Lightweight, fast, and streamer‑friendly.

## Features

- **Animated Overlay**: Tiered colors and subtle motion for that broadcast feel.
- **Witty Quotes**: Randomized feedback per score (e.g., "Butter!", "Did we land or were we shot down?").
- **Text-to-Speech (TTS)**:
  - **Edge TTS** (Default): High-quality neural voices without an API key.
  - **AWS Polly**: Professional neural voices (requires AWS credentials).
  - **System Speech**: Uses your installed Windows voices.
- **Integrated Settings UI**: Configure TTS, voices, and settings directly in the app.
- **Stream Deck / API Support**: Built-in HTTP server accepts `GET /vote/<score>` triggers.
- **Customizable**: Edit `quotes.json` to add your own flavor.

## Screenshots

*(Screenshots to be updated)*

## Quick Start

### Prerequisites
- Windows 10 or 11
- **None** if running the release executable (it's self-contained!).
- .NET 10.0 SDK (only if building from source).

### Running from Release
1. Download the latest release.
2. Run `LandingJudge.exe`.
3. (Optional) Edit `quotes.json` which will be created automatically on first run.

### Running from Source
1. **Clone the repository**:
   ```powershell
   git clone https://github.com/<your-username>/landing-judge.git
   cd landing-judge
   ```

2. **Build Single-File Executable**:
   ```powershell
   dotnet publish LandingJudge.csproj -c Release -r win-x64 -o publish
   ```
   *The executable will be in the `publish` folder in your project root.*

3. **Run**:
   Navigate to the `publish` folder and run `LandingJudge.exe`.
   - The application window will open, showing the **Overlay URL** (e.g., `http://localhost:5000/overlay`).
   - Add this URL as a **Browser Source** in OBS or open it in a web browser.
   - Use the buttons in the app or the HTTP API to trigger votes.

## Configuration

### TTS Settings
You can switch TTS providers in the **Settings** menu:
- **Edge**: Free, high-quality online voices.
- **System**: Offline Windows voices.
- **AWS**: Requires an `.env` file or environment variables with `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION`.

### Custom Quotes
Edit the `quotes.json` file in the application directory to change the feedback messages.
- Categories 1-10 correspond to the landing score.
- Ensure the JSON structure is valid.
- A `quotes.default.json` is provided as a backup.

### API / Stream Deck
You can trigger votes externally (e.g., from a Stream Deck) by making HTTP GET requests:

- Vote 10: `http://localhost:5000/vote/10`
- Vote 5: `http://localhost:5000/vote/5`
- ...and so on.

## Project Structure

- **Root Directory**: Main C# WPF Project
  - **wwwroot/**: Embedded static assets (HTML/CSS/JS) — *baked into the EXE*.
  - **Services/**: Core logic (Vote, TTS, Env).
  - **quotes.default.json**: Embedded default configuration.

## License

MIT License
