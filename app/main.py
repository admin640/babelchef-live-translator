import os
import json
import base64
import logging
import asyncio
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from livekit.api import AccessToken, VideoGrants
from dotenv import load_dotenv

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types
from app.cooking_tools import cooking_tools

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("babelchef")

app = FastAPI(title="BabelChef – Gold Standard")

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Language name map
LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "ja": "Japanese", "ko": "Korean", "zh": "Chinese (Mandarin)",
    "ar": "Arabic", "ru": "Russian", "tr": "Turkish", "nl": "Dutch", "pl": "Polish",
    "th": "Thai", "vi": "Vietnamese", "id": "Indonesian", "ms": "Malay", "bn": "Bengali",
    "ta": "Tamil", "te": "Telugu", "mr": "Marathi", "gu": "Gujarati", "kn": "Kannada",
    "ml": "Malayalam", "pa": "Punjabi", "ur": "Urdu", "sw": "Swahili", "cs": "Czech",
    "ro": "Romanian", "hu": "Hungarian", "el": "Greek", "he": "Hebrew", "fil": "Filipino",
    "uk": "Ukrainian", "sv": "Swedish", "no": "Norwegian", "da": "Danish", "fi": "Finnish",
}

# --- Room state ---
room_participants: dict[str, dict[str, str]] = {}
room_websockets: dict[str, dict[str, WebSocket]] = {}
room_queues: dict[str, dict[str, LiveRequestQueue]] = {}

# --- Cooking assistant state ---
# One cooking assistant per room, shared between both participants
room_cooking_queues: dict[str, LiveRequestQueue] = {}


# ========================================
# Static serving
# ========================================
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open("app/static/index.html", "r") as f:
        return HTMLResponse(content=f.read())


# ========================================
# LiveKit token endpoint (for video only)
# ========================================
class TokenRequest(BaseModel):
    room_name: str
    participant_name: str
    language: Optional[str] = "en"


@app.post("/token")
async def generate_token(req: TokenRequest):
    api_key = os.getenv("LIVEKIT_API_KEY", "devkey")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "secret")

    grant = VideoGrants(
        room_join=True,
        room=req.room_name,
        can_publish=True,
        can_subscribe=True,
    )

    metadata = json.dumps({"language": req.language})

    token = (
        AccessToken(api_key, api_secret)
        .with_identity(req.participant_name)
        .with_name(req.participant_name)
        .with_grants(grant)
        .with_metadata(metadata)
    )

    if req.room_name not in room_participants:
        room_participants[req.room_name] = {}
    room_participants[req.room_name][req.participant_name] = req.language

    livekit_url = os.getenv("LIVEKIT_URL", "wss://babelchef-srrwg26h.livekit.cloud")
    return {"token": token.to_jwt(), "livekit_url": livekit_url}


# ========================================
# Room info endpoint
# ========================================
@app.get("/room-info/{room_id}")
async def get_room_info(room_id: str):
    participants = room_participants.get(room_id, {})
    return {"participants": participants}


# ========================================
# Translation instructions — STRICT, with VIDEO CONTEXT
# ========================================
def build_translation_instructions(source_lang: str, target_lang: str) -> str:
    return (
        f"You are a STRICT real-time speech translator from {source_lang} to {target_lang}.\n\n"
        f"ABSOLUTE RULES — VIOLATION IS FAILURE:\n"
        f"1. ONLY translate speech you actually hear. NEVER generate original content.\n"
        f"2. NEVER predict, guess, or anticipate what the speaker might say.\n"
        f"3. NEVER add greetings, commentary, explanations, acknowledgments, or filler.\n"
        f"4. NEVER respond to questions — translate them verbatim.\n"
        f"5. NEVER make conversation. You are NOT a participant.\n"
        f"6. When you hear SILENCE, produce ABSOLUTE SILENCE. Do NOT speak.\n"
        f"7. When you hear NOISE or UNCLEAR audio, produce SILENCE. Do NOT guess.\n"
        f"8. Translate with 100% fidelity — same tone, intent, and meaning.\n"
        f"9. Output ONLY the {target_lang} translation. Nothing before, nothing after.\n\n"
        f"VIDEO CONTEXT (USE ONLY TO IMPROVE TRANSLATION ACCURACY):\n"
        f"10. You can see video frames from the cooking session. Use visual context ONLY\n"
        f"    to make translations more precise and specific.\n"
        f"11. If the speaker says 'this', 'that', or points at something visible,\n"
        f"    translate using the specific name: 'add this' → 'add the turmeric'.\n"
        f"12. If you see a cooking technique being demonstrated, use the correct term:\n"
        f"    'do it like this' → 'julienne the carrots'.\n"
        f"13. If the speaker references something visible (ingredient, utensil, dish),\n"
        f"    substitute the precise name in the translation.\n"
        f"14. NEVER describe what you see. NEVER comment on the video. NEVER narrate.\n"
        f"    Video is CONTEXT for translation, not content to report.\n\n"
        f"CRITICAL: When in doubt, stay SILENT. Silence is always better than fabrication.\n"
        f"You are invisible. The speakers must feel like they talk directly to each other."
    )


# ========================================
# Cooking Assistant instructions
# ========================================
COOKING_ASSISTANT_INSTRUCTIONS = """
You are a SILENT cooking assistant that watches a live cooking session via video frames.

YOUR JOB: Identify what you see and output SHORT labels. Nothing else.

OUTPUT FORMAT — use EXACTLY this JSON format, one per line:
{"label": "ingredient or technique name", "category": "ingredient|technique|status"}

CATEGORIES:
- ingredient: Spices, vegetables, oils, sauces, utensils visible (e.g., "Turmeric", "Cast Iron Pan")
- technique: Cooking methods being performed (e.g., "Tempering spices", "Julienning")
- status: Doneness or state observations (e.g., "Oil at smoking point", "Onions caramelized")

RULES:
1. Output ONLY when you see something NEW or a significant change.
2. Keep labels SHORT — max 3-4 words.
3. Do NOT repeat labels you already output.
4. Do NOT make conversation or add commentary.
5. Do NOT output anything if the scene hasn't changed.
6. When you see nothing cooking-related, stay COMPLETELY SILENT.
7. Focus on what would be USEFUL for someone cooking along.
"""

APP_NAME = "babelchef-translator"
COOKING_APP_NAME = "babelchef-cooking-assistant"
session_service = InMemorySessionService()
cooking_session_service = InMemorySessionService()


# ========================================
# Cooking Assistant — runs once per room
# ========================================
async def start_cooking_assistant(room_id: str) -> None:
    """Start a cooking assistant agent that watches video and provides insights."""
    if room_id in room_cooking_queues:
        return  # Already running

    session_id = f"cooking_{room_id}"
    user_id = f"cooking_user_{room_id}"

    agent = Agent(
        name="cooking_assistant",
        model="gemini-2.0-flash-live-001",
        description="Identifies ingredients, techniques, and doneness from cooking video",
        instruction=COOKING_ASSISTANT_INSTRUCTIONS,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1,
        ),
    )

    runner = Runner(
        app_name=COOKING_APP_NAME,
        agent=agent,
        session_service=cooking_session_service,
    )

    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["TEXT"],
        session_resumption=types.SessionResumptionConfig(handle=None),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow(target_tokens=1024)
        ),
    )

    session = await cooking_session_service.get_session(
        app_name=COOKING_APP_NAME, user_id=user_id, session_id=session_id
    )
    if not session:
        await cooking_session_service.create_session(
            app_name=COOKING_APP_NAME, user_id=user_id, session_id=session_id
        )

    live_request_queue = LiveRequestQueue()
    room_cooking_queues[room_id] = live_request_queue

    async def cooking_downstream() -> None:
        """Listen for cooking insights and broadcast to all participants."""
        logger.info(f"[CookingAssistant] Started for room {room_id}")
        try:
            async for event in runner.run_live(
                user_id=user_id,
                session_id=session_id,
                live_request_queue=live_request_queue,
                run_config=run_config,
            ):
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text and part.text.strip():
                            text = part.text.strip()
                            logger.info(f"[CookingAssistant] Insight: {text}")

                            # Parse individual lines (agent may output multiple)
                            for line in text.split("\n"):
                                line = line.strip()
                                if not line:
                                    continue

                                # Try to parse as JSON, otherwise wrap as text
                                try:
                                    insight = json.loads(line)
                                    msg = json.dumps({
                                        "type": "cooking_insight",
                                        "label": insight.get("label", line),
                                        "category": insight.get("category", "ingredient"),
                                    })
                                except json.JSONDecodeError:
                                    msg = json.dumps({
                                        "type": "cooking_insight",
                                        "label": line,
                                        "category": "ingredient",
                                    })

                                # Broadcast to all participants in the room
                                ws_map = room_websockets.get(room_id, {})
                                for ws in ws_map.values():
                                    try:
                                        await ws.send_text(msg)
                                    except Exception:
                                        pass

        except Exception as e:
            logger.error(f"[CookingAssistant] Error: {e}", exc_info=True)
        finally:
            room_cooking_queues.pop(room_id, None)
            logger.info(f"[CookingAssistant] Stopped for room {room_id}")

    asyncio.create_task(cooking_downstream())


# ========================================
# ADK Bidi Streaming — CROSS-WIRED + VIDEO CONTEXT
# ========================================
@app.websocket("/ws/translate/{room_id}/{participant_id}")
async def websocket_translate(
    websocket: WebSocket,
    room_id: str,
    participant_id: str,
    source_lang: str = "en",
    target_lang: str = "hi",
) -> None:
    """WebSocket endpoint for bidirectional audio translation via ADK.

    CROSS-WIRED + VIDEO CONTEXT:
    - Audio: A's speech → ADK translates → sent to B (and vice versa)
    - Video: frames sent as JPEG → fed to ADK for translation context
    - Cooking: frames also fed to cooking assistant for ingredient identification
    """
    await websocket.accept()

    source_lang_name = LANGUAGE_NAMES.get(source_lang, source_lang)
    target_lang_name = LANGUAGE_NAMES.get(target_lang, target_lang)
    session_label = f"{source_lang_name}→{target_lang_name}"
    session_id = f"{room_id}_{participant_id}_{source_lang}_{target_lang}"
    user_id = f"user_{participant_id}"

    logger.info(f"[{session_label}] WebSocket connected: {participant_id}")

    # Register WebSocket
    if room_id not in room_websockets:
        room_websockets[room_id] = {}
    room_websockets[room_id][participant_id] = websocket

    if room_id not in room_queues:
        room_queues[room_id] = {}

    # Start cooking assistant if not already running
    await start_cooking_assistant(room_id)

    # Create ADK Agent with video-enhanced translation instructions
    instructions = build_translation_instructions(source_lang_name, target_lang_name)
    agent = Agent(
        name=f"translator_{source_lang}_to_{target_lang}",
        model="gemini-live-2.5-flash-native-audio",
        description=f"Translates {source_lang_name} speech to {target_lang_name} with video context",
        instruction=instructions,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.0,
            thinking_config=types.ThinkingConfig(
                thinking_budget=512,
            ),
        ),
        tools=cooking_tools,
    )

    runner = Runner(
        app_name=APP_NAME,
        agent=agent,
        session_service=session_service,
    )

    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
        # Session stability — survive 10-min WebSocket limits
        session_resumption=types.SessionResumptionConfig(handle=None),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow(target_tokens=1024)
        ),
        # Dual-language subtitles via built-in transcription
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # Emotional tone preservation (Mom's excitement survives translation)
        enable_affective_dialog=True,
        # Native silence detection (no more sizzle/chop phantom translations)
        proactivity=types.ProactivityConfig(proactive_audio=True),
    )

    session = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if not session:
        await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )

    live_request_queue = LiveRequestQueue()
    room_queues[room_id][participant_id] = live_request_queue

    def get_other_ws() -> Optional[WebSocket]:
        ws_map = room_websockets.get(room_id, {})
        for pid, ws in ws_map.items():
            if pid != participant_id:
                return ws
        return None

    # --- Upstream: audio + video frames from client → ADK ---
    async def upstream_task() -> None:
        logger.info(f"[{session_label}] Upstream started for {participant_id}")
        try:
            while True:
                message = await websocket.receive()

                if "bytes" in message:
                    # Binary = PCM audio
                    audio_blob = types.Blob(
                        mime_type="audio/pcm;rate=16000",
                        data=message["bytes"],
                    )
                    live_request_queue.send_realtime(audio_blob)

                elif "text" in message:
                    try:
                        json_msg = json.loads(message["text"])
                        msg_type = json_msg.get("type")

                        if msg_type == "image":
                            # Video frame → feed to translation agent AND cooking assistant
                            image_data = base64.b64decode(json_msg["data"])
                            mime_type = json_msg.get("mimeType", "image/jpeg")

                            image_blob = types.Blob(
                                mime_type=mime_type,
                                data=image_data,
                            )

                            # Feed to translation agent for visual context
                            live_request_queue.send_realtime(image_blob)

                            # Feed to cooking assistant
                            cooking_queue = room_cooking_queues.get(room_id)
                            if cooking_queue:
                                cooking_queue.send_realtime(image_blob)

                            logger.debug(f"[{session_label}] Video frame sent to agents")

                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(f"[{session_label}] Bad JSON: {e}")

        except WebSocketDisconnect:
            logger.info(f"[{session_label}] Client disconnected (upstream): {participant_id}")
        except Exception as e:
            logger.error(f"[{session_label}] Upstream error: {e}", exc_info=True)

    # --- Downstream: translated audio/text from ADK → other participant ---
    async def broadcast_text(msg_json: str) -> None:
        """Send a JSON text message to BOTH participants."""
        try:
            await websocket.send_text(msg_json)
        except Exception:
            pass
        other_ws = get_other_ws()
        if other_ws:
            try:
                await other_ws.send_text(msg_json)
            except Exception:
                pass

    async def downstream_task() -> None:
        logger.info(f"[{session_label}] Downstream started for {participant_id}")
        try:
            async for event in runner.run_live(
                user_id=user_id,
                session_id=session_id,
                live_request_queue=live_request_queue,
                run_config=run_config,
            ):
                # Debug: log event fields to trace transcription flow
                event_fields = [attr for attr in dir(event) if not attr.startswith('_')]
                logger.debug(f"[{session_label}] Event fields: {event_fields}")

                # --- Built-in audio transcription (input = original speech) ---
                if hasattr(event, 'input_transcription') and event.input_transcription:
                    text = getattr(event.input_transcription, 'text', '')
                    if text and text.strip():
                        await broadcast_text(json.dumps({
                            "type": "input_transcription",
                            "text": text.strip(),
                            "source_lang": source_lang,
                            "target_lang": target_lang,
                        }))
                        logger.info(f"[{session_label}] Input transcription sent: {text.strip()[:50]}")

                # --- Built-in audio transcription (output = translated speech) ---
                if hasattr(event, 'output_transcription') and event.output_transcription:
                    text = getattr(event.output_transcription, 'text', '')
                    if text and text.strip():
                        await broadcast_text(json.dumps({
                            "type": "output_transcription",
                            "text": text.strip(),
                            "source_lang": source_lang,
                            "target_lang": target_lang,
                        }))
                        logger.info(f"[{session_label}] Output transcription sent: {text.strip()[:50]}")

                # --- Content parts (audio + fallback text transcriptions) ---
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        # Audio → send to OTHER participant
                        if (
                            part.inline_data
                            and part.inline_data.mime_type
                            and part.inline_data.mime_type.startswith("audio/pcm")
                        ):
                            other_ws = get_other_ws()
                            if other_ws:
                                try:
                                    await other_ws.send_bytes(part.inline_data.data)
                                except Exception as send_err:
                                    logger.warning(f"[{session_label}] Send to other failed: {send_err}")

                        # Text from parts → fallback subtitles
                        elif part.text:
                            await broadcast_text(json.dumps({
                                "type": "transcription",
                                "text": part.text,
                                "direction": f"{source_lang}→{target_lang}",
                                "source_lang": source_lang,
                                "target_lang": target_lang,
                            }))

        except WebSocketDisconnect:
            logger.info(f"[{session_label}] Client disconnected (downstream): {participant_id}")
        except Exception as e:
            logger.error(f"[{session_label}] Downstream error: {e}", exc_info=True)

    # Run both tasks
    try:
        await asyncio.gather(upstream_task(), downstream_task())
    except Exception as e:
        logger.error(f"[{session_label}] Session error: {e}", exc_info=True)
    finally:
        logger.info(f"[{session_label}] Cleaning up: {participant_id}")
        live_request_queue.close()
        room_websockets.get(room_id, {}).pop(participant_id, None)
        room_queues.get(room_id, {}).pop(participant_id, None)
        # If no more participants, close cooking assistant
        if not room_websockets.get(room_id):
            cooking_queue = room_cooking_queues.pop(room_id, None)
            if cooking_queue:
                cooking_queue.close()
