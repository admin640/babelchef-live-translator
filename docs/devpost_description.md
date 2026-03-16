# BabelChef — DevPost Submission Text

## Summary

BabelChef is a real-time bilingual video call translator purpose-built for cross-cultural cooking. When Mom speaks Hindi and daughter-in-law speaks English, BabelChef bridges the gap so they can cook biryani together — guided by voice, face-to-face on video, with AI that understands what's happening in the kitchen.

## The Problem

700 million people worldwide live in multilingual family households. When a Hindi-speaking grandmother wants to teach her English-speaking daughter-in-law how to make biryani over a video call, no existing tool works:

- **Google Translate**: Text-based, turn-by-turn — too slow for "Add the spices NOW!"
- **Video calls** (FaceTime, WhatsApp): No translation
- **Interpreter apps**: No video, no visual context
- **Kitchen noise problem**: Sizzling oil, clattering utensils, and running water trigger phantom translations
- **Session drops**: Cooking sessions last 30-60 minutes, exceeding typical API session limits

## The Solution

BabelChef creates a video call where each person speaks their own language and hears the other in theirs — in real-time, with emotional tone preserved, and with AI that understands cooking context.

## 7 Gold Standard Gemini Live API Features

1. **Session Resumption** — Long cooking sessions survive WebSocket connection limits
2. **Context Window Compression** — Unlimited session length without memory degradation
3. **Input Audio Transcription** — Shows original speech as subtitles
4. **Output Audio Transcription** — Shows translated speech as subtitles
5. **Affective Dialog** — Preserves emotional tone: excitement, urgency, tenderness
6. **Proactive Audio** — Filters kitchen noise — sizzling, chopping, clattering don't trigger phantom translations
7. **Function Calling (Cooking Tools)** — Mid-conversation measurement conversion ("How many grams is 2 cups?"), timer suggestions, and culturally-aware cooking term explanations ("What does tadka mean?")

Additionally, Thinking Config enables contextually accurate translations of cooking idioms rather than literal word-for-word translations.

## Technologies Used

- **Gemini Live 2.5 Flash Native Audio** — Bidirectional real-time translation with native audio I/O
- **Gemini 2.0 Flash Live** — Cooking assistant agent (text output for insight badges)
- **ADK (Agent Development Kit)** — Bidi streaming via `LiveRequestQueue` + `run_live()`, function calling
- **Google Cloud Run** — Serverless container hosting with WebSocket support + session affinity
- **Vertex AI** — Gemini model serving (us-central1)
- **FastAPI** — Python web framework with WebSocket support
- **Web Audio API** — Browser-based PCM audio capture and playback (16kHz mono)

## Architecture

The system runs three concurrent ADK agents per room:

1. **EN→HI Translation Agent**: Receives English audio + video frames, outputs Hindi audio with emotional tone preservation
2. **HI→EN Translation Agent**: Receives Hindi audio + video frames, outputs English audio
3. **Cooking Assistant**: Watches video from both cameras, identifies ingredients/techniques, provides cultural cooking insights as text badges

All agents use ADK's `run_live()` for bidirectional streaming with automatic session management, tool invocation, and transcription.

## Findings & Learnings

1. **Native audio models cannot output text** — The cooking assistant needed `gemini-2.0-flash-live-001` (text-capable) while translation agents use `gemini-live-2.5-flash-native-audio` (audio-only)
2. **Proactive Audio is a game-changer** — Kitchen environments are noisy. Without it, sizzling pans and running water generate phantom translations. With Proactive Audio, only intentional speech triggers translation.
3. **Session Resumption is essential for real-world cooking** — A typical biryani takes 45-60 minutes. Without session resumption, the connection drops and context is lost.
4. **Affective dialog makes translation feel human** — When Mom excitedly says "Wah! Bahut accha!" the translation preserves the joy, not just the words.
5. **Vision context improves translation accuracy** — When someone says "that looks done," the AI sees what "that" refers to in the video frame.
6. **Vertex AI model names differ from AI Studio** — This caused runtime errors until we mapped the correct model IDs for the Live API.

## Third-Party Integrations

- **LiveKit** (livekit.io): WebRTC infrastructure for video relay between participants. Used under their standard API terms.
- **Google Cloud Run**: Container hosting with WebSocket support
- **Vertex AI**: Gemini model access

All other components are original work built during the contest period.
