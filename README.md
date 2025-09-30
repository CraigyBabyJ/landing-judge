# 🛬 Landing Voting System

A real-time overlay system for rating aircraft landings with animated displays, sarcastic quotes, and text-to-speech feedback. Perfect for streaming or recording flight simulations.

## 📺 What It Does

This system creates a transparent overlay that displays animated landing scores (1-10) with:
- **Animated score displays** with dynamic entrance effects
- **Sarcastic quotes** based on landing quality
- **Color-coded feedback** (red=bad, amber=ok, yellow=good, green=great)
- **Audio playback** of quotes using AWS Polly text-to-speech
- **Real-time updates** via Server-Sent Events (SSE)
- **OBS-ready transparent overlay** (1080x1920 resolution)

## 🚀 Quick Start

### Prerequisites
- Python 3.7+
- Flask
- boto3 (for AWS Polly audio)
- python-dotenv

### Installation
1. Install dependencies:
```bash
pip install flask boto3 python-dotenv
```

2. Run the server:
```bash
python app.py
```

3. Open the overlay in your browser:
```
http://127.0.0.1:5005/overlay
```

### Testing the System
Trigger a vote to see the animated overlay:
```bash
# Windows PowerShell
Invoke-WebRequest -Uri "http://127.0.0.1:5005/vote/7"

# Or use curl
curl "http://127.0.0.1:5005/vote/7"
```

## 🎯 Endpoints

| Endpoint | Method | Description |
|----------|---------|-------------|
| `/` | GET | Redirects to overlay |
| `/overlay` | GET | Main overlay page (transparent, OBS-ready) |
| `/vote/<score>` | GET | Submit a landing vote (1-10) |
| `/stats` | GET | Get voting statistics (JSON) |
| `/stream` | GET | SSE stream for real-time updates |
| `/reset` | POST | Reset/refresh overlay |

## 🛠️ Configuration

### Environment Variables
Create a `.env` file in the project root:

```env
# Server Settings
PORT=5005
BANNER_DURATION_MS=8000
DATA_FILE=landings.json

# AWS Polly (optional - for audio quotes)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1
POLLY_VOICE_ID=Joanna
POLLY_OUTPUT_FORMAT=mp3
```

### Quote System
Add custom quotes in `quotes.json`:
```json
{
  "quotes": {
    "1": ["That was... educational.", "Physics called - they want an explanation."],
    "10": ["Absolute butter!", "Chief pilot approved!"]
  }
}
```

## 📁 Project Structure

```
votelandings/
├── app.py              # Main Flask application
├── templates/
│   └── overlay.html    # Overlay template
├── static/
│   ├── style.css       # Overlay styling & animations
│   ├── overlay.js      # Real-time overlay logic
│   └── *.mp3          # Generated audio files (auto-created)
├── quotes.json         # Custom quote definitions
├── landings.json       # Vote data storage (auto-created)
├── .env               # Environment configuration
└── README.md          # This file
```

## 🎨 Features

### Score Categories
- **1-3 (Bad)**: Red color scheme - "Mayday? That was... educational."
- **4-6 (OK)**: Amber color scheme - "Not bad, not smooth. We felt it."
- **7-8 (Good)**: Yellow color scheme - "Nice! Most passengers missed it."
- **9-10 (Great)**: Green color scheme - "Absolute butter. Chief pilot approved!"

### Animation Effects
The overlay includes 11 different entrance animations:
- Spin in from distance
- Flip in from far
- Bounce from corner
- Slide from edges
- Zoom spin from space
- Elastic from distance
- Spiral from edge
- Twist from void

### Audio Integration
- Automatic text-to-speech using AWS Polly
- Generated audio files cached locally
- Fallback graceful handling if AWS not configured

## 🔧 OBS Setup

1. Add a **Browser Source** in OBS
2. Set URL to: `http://127.0.0.1:5005/overlay`
3. Set dimensions: **1080x1920** (or adjust for your stream)
4. Check **Shutdown source when not visible**
5. Check **Refresh browser when scene becomes active**

## 🐛 Troubleshooting

### "Overlay isn't working"
✅ **The overlay IS working** - here's how to verify:

1. **Check if server is running**:
```powershell
netstat -an | findstr :5005
```
Should show: `TCP 127.0.0.1:5005 0.0.0.0:0 LISTENING`

2. **Test the overlay endpoint**:
```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:5005/overlay"
```
Should return HTML with 200 OK status.

3. **The overlay appears blank** - This is **normal behavior**!
   - The overlay is transparent until a vote is cast
   - Trigger a test vote: `Invoke-WebRequest -Uri "http://127.0.0.1:5005/vote/7"`
   - You should see an animated "7/10" appear

### Common Issues

**Blank/Transparent Overlay**
- ✅ This is correct! The overlay only shows content when votes are triggered
- Test with: `http://127.0.0.1:5005/vote/8`

**Static Files Not Loading**
- Check: `http://127.0.0.1:5005/static/style.css`
- Check: `http://127.0.0.1:5005/static/overlay.js`

**No Audio**
- AWS credentials needed for text-to-speech
- System will work without audio if AWS not configured

**Browser Compatibility**
- Chrome/Edge: Full support
- Firefox: Full support
- Safari: Limited SSE support
- Try hard refresh: Ctrl+F5

## 📊 API Examples

### Vote for a Landing
```bash
# Score of 8/10
curl "http://127.0.0.1:5005/vote/8"

# Response:
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

### Get Statistics
```bash
curl "http://127.0.0.1:5005/stats"

# Response:
{
  "count": 15,
  "average": 6.8,
  "best": 10,
  "recent": [7, 8, 5, 9, 6],
  "top": [10, 10, 9, 9, 8]
}
```

## 🔌 Integration Ideas

- **Twitch Bot**: Viewers vote via chat commands
- **Discord Bot**: Server members rate landings
- **Hardware Integration**: Physical buttons/switches
- **Game Integration**: Auto-trigger based on sim telemetry
- **Multi-overlay**: Different scenes for different games

## 📝 Development

### Running in Development
```bash
python app.py
```
Server runs on `http://127.0.0.1:5005` with threading enabled for SSE support.

### File Modifications
- **Templates**: Modify `templates/overlay.html`
- **Styling**: Edit `static/style.css`
- **Animations**: Update `static/overlay.js`
- **Quotes**: Customize `quotes.json`

## 🤝 Contributing

Feel free to submit issues, feature requests, or pull requests to improve the system!

## 📄 License

This project is provided as-is for educational and entertainment purposes.

---

## 🎮 Ready to Rate Some Landings?

1. **Start the server**: `python app.py`
2. **Open overlay**: http://127.0.0.1:5005/overlay
3. **Test a vote**: http://127.0.0.1:5005/vote/7
4. **Watch the magic**: Animated scores with sassy quotes!

**Pro Tip**: The overlay is designed to be transparent - if you see "nothing", that means it's working perfectly and waiting for votes! 🛬✨