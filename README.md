# 🍳 BabelChef — Real-Time Bilingual Video Call Translator

> Mom speaks Hindi, wife speaks English. BabelChef uses Gemini Live API to translate their video call in real-time — so Mom can guide her through biryani, spice by spice.

[![Category](https://img.shields.io/badge/Category-Live%20Agents-e94560)](https://geminiliveagentchallenge.devpost.com/)
[![Built with](https://img.shields.io/badge/Built%20with-Gemini%20Live%20API%20%2B%20ADK-4285F4)](https://google.github.io/adk-docs/)
[![Hosted on](https://img.shields.io/badge/Hosted%20on-Google%20Cloud%20Run-34A853)](https://cloud.google.com/run)

---

## 🎯 The Problem

When two family members speak different languages, existing tools fail for real-time, collaborative tasks like cooking:

- **Google Translate**: Text-based, turn-by-turn — too slow for "Add the spices NOW!"
- **Video calls** (FaceTime, WhatsApp): No translation at all
- **Interpreter apps**: No video, no visual context

BabelChef bridges this gap with **vision-aware, real-time audio translation over video calls**.

## ✨ How It Works

Two people join a video call, each speaking their own language. Gemini translates in real-time:

1. **Wife speaks English** → audio sent to EN→HI Gemini Agent → Mom hears Hindi
2. **Mom speaks Hindi** → audio sent to HI→EN Gemini Agent → Wife hears English
3. **Camera feeds** are relayed directly AND sent to Gemini for **visual context** — so when Mom says "that looks done," the AI understands *what* she's looking at

## 🏗️ Architecture

![Architecture Diagram](docs/architecture.png)

```
Wife's Device ←→ [WebSocket] ←→ Cloud Run: BabelChef ←→ [WebSocket] ←→ Mom's Device
                                    │
                                    ├── EN→HI Agent (Gemini Live API + Vision)
                                    ├── HI→EN Agent (Gemini Live API + Vision)
                                    └── Video Frame Relay
```

### Key Technical Decisions

| Decision | Choice | Why |
|---|---|---|
| **Two separate agents** | EN→HI + HI→EN | Independent pipelines prevent crosstalk and allow different voice configs |
| **Vision-aware translation** | Video frames sent to Gemini | Contextual translation: "that's ready" → understands what "that" refers to |
| **ADK bidi-streaming** | `LiveRequestQueue` + `run_live()` | Handles interruptions, concurrent streams, state management |
| **FastAPI + WebSocket** | Long-lived connections | Real-time audio/video streaming (not possible with HTTP request/response) |
| **Cloud Run** | Session affinity enabled | WebSocket support with auto-scaling |

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Google Cloud project with Vertex AI API enabled
- Google Cloud Application Default Credentials (`gcloud auth application-default login`)

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/babelchef-live-translator.git
cd babelchef-live-translator

# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install dependencies
uv venv && source .venv/bin/activate
uv pip install -e .
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your Google Cloud project details
```

**Option A: Google AI Studio (quickest for development)**
```
GOOGLE_API_KEY=your-api-key
```

**Option B: Vertex AI (for production / Cloud Run)**
```
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=TRUE
```

### 3. Run Locally

```bash
uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080 in your browser.

### 4. Test a Call

1. Open two browser tabs at http://localhost:8080
2. **Tab 1**: Select "English Speaker" → Click "Create New Room" → Note the room code
3. **Tab 2**: Select "Hindi Speaker" → Enter the room code → Click "Join"
4. Both tabs switch to the call screen — start speaking!

## ☁️ Deploy to Cloud Run

```bash
chmod +x deploy.sh
./deploy.sh
```

Or manually:

```bash
gcloud run deploy babelchef-live-translator \
    --source . \
    --region us-central1 \
    --allow-unauthenticated \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=your-project,GOOGLE_CLOUD_LOCATION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=TRUE" \
    --session-affinity \
    --timeout 3600
```

## 📁 Project Structure

```
babelchef-live-translator/
├── app/
│   ├── agents/
│   │   ├── __init__.py
│   │   └── translator_agent.py    # EN→HI + HI→EN ADK agents
│   ├── room_manager.py            # Call room lifecycle
│   ├── main.py                    # FastAPI + WebSocket server
│   └── static/                    # Web demo client
│       ├── index.html
│       ├── css/style.css
│       └── js/
│           ├── app.js             # Room/call management
│           └── audio-processor.js # PCM recording & playback
├── Dockerfile
├── deploy.sh
├── pyproject.toml
├── .env.example
└── README.md
```

## 🛠️ Built With

- **[Google ADK](https://google.github.io/adk-docs/)** — Agent Development Kit for bidi-streaming
- **[Gemini 2.0 Flash Live API](https://ai.google.dev/gemini-api/docs/live)** — Real-time multimodal AI
- **[FastAPI](https://fastapi.tiangolo.com/)** — Python web framework with WebSocket support
- **[Google Cloud Run](https://cloud.google.com/run)** — Serverless container hosting
- **Web Audio API** — Browser-based audio capture and playback

## 📄 License

Apache 2.0

---

*Built for the [Gemini Live Agent Challenge](https://geminiliveagentchallenge.devpost.com/) 🏆*
