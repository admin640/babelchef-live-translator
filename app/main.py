"""BabelChef — Real-time bilingual video call translator.

FastAPI application with WebSocket endpoints for bidirectional
audio/video streaming through Gemini Live API translation agents.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.adk.agents import LiveRequestQueue
from google.genai import types

from app.room_manager import RoomManager, ParticipantRole

load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── FastAPI app ──────────────────────────────────────────────────────────

app = FastAPI(
    title="BabelChef Live Translator",
    description="Real-time bilingual video call translation via Gemini Live API",
    version="0.1.0",
)

# Serve static web demo client
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Global room manager
room_manager = RoomManager()


# ── REST endpoints ───────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the web demo client."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    with open(index_path) as f:
        return HTMLResponse(content=f.read())


@app.get("/health")
async def health():
    """Health check for Cloud Run."""
    return {"status": "healthy", "service": "babelchef-live-translator"}


@app.post("/rooms")
async def create_room():
    """Create a new call room."""
    room = await room_manager.create_room()
    return {"room_id": room.room_id}


@app.get("/rooms")
async def list_rooms():
    """List active rooms."""
    return {"rooms": room_manager.list_rooms()}


@app.get("/rooms/{room_id}")
async def get_room(room_id: str):
    """Get room details."""
    room = room_manager.get_room(room_id)
    if room is None:
        return JSONResponse(status_code=404, content={"error": "Room not found"})
    return {
        "room_id": room.room_id,
        "participants": len(room.participants),
        "is_full": room.is_full,
    }


# ── WebSocket endpoint ──────────────────────────────────────────────────

@app.websocket("/ws/{room_id}/{role}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, role: str):
    """WebSocket endpoint for a call participant.

    URL: /ws/{room_id}/{role}
    role: "english" or "hindi"

    Message format (JSON):
        Audio:   {"type": "audio", "data": "<base64 PCM>"}
        Video:   {"type": "video", "data": "<base64 JPEG frame>"}
        Text:    {"type": "text", "text": "hello"}
        Control: {"type": "control", "action": "end_call"}

    Or binary messages are treated as raw audio PCM data.
    """
    await websocket.accept()

    # Validate role
    try:
        participant_role = ParticipantRole(role)
    except ValueError:
        await websocket.send_json({"error": f"Invalid role: {role}. Use 'english' or 'hindi'"})
        await websocket.close()
        return

    participant_id = str(uuid.uuid4())[:8]

    # Join the room
    try:
        room = await room_manager.join_room(
            room_id=room_id,
            participant_id=participant_id,
            role=participant_role,
            websocket=websocket,
        )
    except ValueError as e:
        await websocket.send_json({"error": str(e)})
        await websocket.close()
        return

    await websocket.send_json({
        "type": "joined",
        "participant_id": participant_id,
        "role": role,
        "room_id": room_id,
    })

    logger.info("WS connected: participant=%s role=%s room=%s", participant_id, role, room_id)

    # Wait until room is full (both participants joined)
    while not room.is_full:
        await websocket.send_json({"type": "waiting", "message": "Waiting for other participant..."})
        await asyncio.sleep(1)
        # Re-check room (might have been destroyed)
        room = room_manager.get_room(room_id)
        if room is None:
            await websocket.close()
            return

    await websocket.send_json({"type": "call_started", "message": "Both participants connected!"})

    # Determine which pipeline this participant feeds into
    # English speaker → feeds EN→HI pipeline (their speech gets translated to Hindi)
    # Hindi speaker → feeds HI→EN pipeline (their speech gets translated to English)
    if participant_role == ParticipantRole.ENGLISH_SPEAKER:
        my_pipeline = room.en_to_hi_pipeline  # my speech → translated for other
        their_pipeline = room.hi_to_en_pipeline  # other's speech → translated for me
    else:
        my_pipeline = room.hi_to_en_pipeline
        their_pipeline = room.en_to_hi_pipeline

    if my_pipeline is None or their_pipeline is None:
        await websocket.send_json({"error": "Translation pipelines not ready"})
        await websocket.close()
        return

    # ── Concurrent tasks ─────────────────────────────────────────────

    async def upstream_task():
        """Receive audio/video from this participant → feed to translation agent."""
        try:
            while True:
                try:
                    # Try to receive JSON message first
                    raw = await websocket.receive()
                except WebSocketDisconnect:
                    logger.info("WS disconnected: %s", participant_id)
                    break

                if "text" in raw:
                    msg = json.loads(raw["text"])
                    msg_type = msg.get("type", "text")

                    if msg_type == "audio":
                        # Base64 audio → send to translation pipeline
                        audio_data = base64.b64decode(msg["data"])
                        blob = types.Blob(
                            mime_type="audio/pcm;rate=16000",
                            data=audio_data,
                        )
                        my_pipeline.live_queue.send_realtime(blob)

                    elif msg_type == "video":
                        # Base64 video frame → send to translation agent for context
                        # AND relay to other participant directly
                        video_data = base64.b64decode(msg["data"])

                        # Send to Gemini for visual context
                        blob = types.Blob(
                            mime_type="image/jpeg",
                            data=video_data,
                        )
                        my_pipeline.live_queue.send_realtime(blob)

                        # Relay video frame to other participant
                        other = room.other_participant(participant_id)
                        if other and other.websocket:
                            try:
                                await other.websocket.send_json({
                                    "type": "video",
                                    "data": msg["data"],  # Forward as-is (base64)
                                })
                            except Exception:
                                pass  # Other participant might have disconnected

                    elif msg_type == "text":
                        # Text input → send as content to pipeline
                        content = types.Content(
                            parts=[types.Part(text=msg.get("text", ""))],
                            role="user",
                        )
                        my_pipeline.live_queue.send_content(content)

                    elif msg_type == "control":
                        if msg.get("action") == "end_call":
                            break

                elif "bytes" in raw:
                    # Raw binary → treat as PCM audio
                    blob = types.Blob(
                        mime_type="audio/pcm;rate=16000",
                        data=raw["bytes"],
                    )
                    my_pipeline.live_queue.send_realtime(blob)

        except Exception as e:
            logger.error("Upstream error for %s: %s", participant_id, e)

    async def downstream_task():
        """Receive translated audio from Gemini → send to this participant.

        This listens to the OTHER participant's translation pipeline,
        because that pipeline translates the other person's speech for us.
        """
        try:
            async for event in their_pipeline.runner.run_live(
                session=their_pipeline.session,
                live_request_queue=their_pipeline.live_queue,
                run_config=their_pipeline.run_config,
            ):
                # Process events from Gemini
                if hasattr(event, "content") and event.content:
                    for part in event.content.parts:
                        if hasattr(part, "inline_data") and part.inline_data:
                            # Audio response → send to this participant
                            audio_b64 = base64.b64encode(
                                part.inline_data.data
                            ).decode("utf-8")
                            try:
                                await websocket.send_json({
                                    "type": "audio",
                                    "data": audio_b64,
                                    "mime_type": part.inline_data.mime_type,
                                })
                            except Exception:
                                break

                        elif hasattr(part, "text") and part.text:
                            # Text transcript → send as subtitle
                            try:
                                await websocket.send_json({
                                    "type": "subtitle",
                                    "text": part.text,
                                })
                            except Exception:
                                break

                # Also forward server events for debugging
                if hasattr(event, "server_content"):
                    try:
                        await websocket.send_json({
                            "type": "event",
                            "data": str(event),
                        })
                    except Exception:
                        break

        except Exception as e:
            logger.error("Downstream error for %s: %s", participant_id, e)

    # Run upstream and downstream concurrently
    try:
        upstream = asyncio.create_task(upstream_task())
        downstream = asyncio.create_task(downstream_task())

        # Wait for either to complete (usually upstream ends when WS disconnects)
        done, pending = await asyncio.wait(
            [upstream, downstream],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel the other task
        for task in pending:
            task.cancel()

    finally:
        # Cleanup
        await room_manager.leave_room(room_id, participant_id)

        # Notify other participant
        other = room.other_participant(participant_id) if room else None
        if other and other.websocket:
            try:
                await other.websocket.send_json({
                    "type": "control",
                    "action": "participant_left",
                })
            except Exception:
                pass

        logger.info("WS cleanup complete: %s", participant_id)


# ── Run ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
