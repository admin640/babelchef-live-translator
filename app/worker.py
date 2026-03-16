import os
import json
import logging
import asyncio
from dotenv import load_dotenv

from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    JobExecutorType,
    cli,
    llm,
    AgentSession,
    Agent,
)
from livekit.agents.voice.room_io import RoomOptions
from livekit.agents.voice.room_io.types import AudioOutputOptions
from livekit.agents.voice import events
from livekit.plugins import google

load_dotenv()
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("babelchef-worker")

# Full language name map
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


def get_participant_language(participant) -> tuple[str, str]:
    """Extract language code and name from participant metadata.
    Returns (lang_code, lang_name), e.g. ('hi', 'Hindi')."""
    meta = participant.metadata
    if meta:
        try:
            data = json.loads(meta)
            lang_code = data.get("language", "en")
            lang_name = LANGUAGE_NAMES.get(lang_code, lang_code)
            return (lang_code, lang_name)
        except (json.JSONDecodeError, AttributeError):
            pass
    return ("en", "English")


def build_translation_instructions(source_lang: str, target_lang: str) -> str:
    """Build STRICT translation-only instructions. No hallucination, no predictions."""
    return (
        f"You are a STRICT real-time speech translator from {source_lang} to {target_lang}. "
        f"Your ONLY job is to translate what the speaker says. Follow these rules EXACTLY:\n\n"
        f"CORE RULES:\n"
        f"1. ONLY translate speech you actually hear. Do NOT generate any original content.\n"
        f"2. Do NOT predict what the speaker will say next.\n"
        f"3. Do NOT add greetings, commentary, explanations, or filler words.\n"
        f"4. Do NOT respond to questions — just translate them.\n"
        f"5. Do NOT make conversation — you are a transparent translation layer.\n"
        f"6. If you hear silence, stay COMPLETELY silent. Do NOT speak unless you hear speech.\n"
        f"7. Translate as faithfully as possible. Keep the same tone and intent.\n"
        f"8. If you hear noise or unclear audio, stay silent. Do NOT guess.\n"
        f"9. Output ONLY the {target_lang} translation. Nothing else.\n\n"
        f"VIDEO CONTEXT RULES:\n"
        f"10. You can see the speaker's video. Use it ONLY to improve translation accuracy.\n"
        f"11. If the speaker says 'this' or 'that' while pointing at something visible, "
        f"translate with the specific name (e.g., 'add this' → 'add the cumin').\n"
        f"12. If the speaker demonstrates a cooking technique, use the correct term "
        f"(e.g., 'do it like this' → 'julienne the carrots').\n"
        f"13. NEVER describe what you see unless the speaker explicitly asks. "
        f"NEVER comment on the video unprompted.\n\n"
        f"You are invisible. The speakers should feel like they are talking directly to each other."
    )


async def create_session_for_participant(
    ctx: JobContext,
    source_participant: rtc.RemoteParticipant,
    source_lang_name: str,
    target_lang_code: str,
    target_lang_name: str,
    session_label: str,
    track_source: int,
):
    """Create an AgentSession that listens to source_participant and translates to target language.
    Audio output is tagged with 'translation-{target_lang_code}' so frontend can filter.
    Uses different track_source for each session to avoid LiveKit deduplication."""

    instructions = build_translation_instructions(source_lang_name, target_lang_name)
    track_name = f"translation-{target_lang_code}"
    logger.info(f"[{session_label}] Creating session for {source_participant.identity}")
    logger.info(f"[{session_label}] Audio track name: {track_name}, source: {track_source}")

    # LOW temperature for faithful translation — no creativity/hallucination
    gemini_realtime = google.beta.realtime.RealtimeModel(
        model="gemini-2.5-flash-native-audio-preview-12-2025",
        voice="Puck",
        temperature=0.2,
    )

    agent = Agent(instructions=instructions)
    session = AgentSession(llm=gemini_realtime)

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(ev):
        if ev.is_final and ev.transcript:
            logger.info(f"[{session_label}] USER TRANSCRIPT ({source_lang_name}): {ev.transcript}")
            asyncio.create_task(
                ctx.room.local_participant.publish_data(
                    ev.transcript.encode("utf-8"),
                    topic="transcription",
                )
            )

    @session.on("agent_state_changed")
    def on_agent_state(ev):
        logger.info(f"[{session_label}] AGENT STATE: {ev.old_state} -> {ev.new_state}")

    @session.on("conversation_item_added")
    def on_conversation_item_added(ev):
        role = getattr(ev.item, "role", "unknown")
        if role == "assistant":
            content = getattr(ev.item, "content", None)
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = []
                for p in content:
                    if isinstance(p, str):
                        parts.append(p)
                    elif hasattr(p, "text") and p.text:
                        parts.append(p.text)
                text = " ".join(parts)
            if text:
                logger.info(f"[{session_label}] TRANSLATION ({target_lang_name}): {text}")
                asyncio.create_task(
                    ctx.room.local_participant.publish_data(
                        text.encode("utf-8"),
                        topic="transcription_translation",
                    )
                )

    @session.on("error")
    def on_error(ev):
        logger.error(f"[{session_label}] SESSION ERROR: {ev}")

    @session.on("close")
    def on_close(ev):
        logger.warning(f"[{session_label}] SESSION CLOSED: {ev}")

    # Start session linked to THIS specific participant
    # Tag the audio output with target language so frontend can filter
    # Use different track_source for each session to avoid LiveKit replacing the first track
    await session.start(
        agent,
        room=ctx.room,
        room_options=RoomOptions(
            video_input=True,  # Enable video for visual context (better translations)
            participant_identity=source_participant.identity,
            audio_output=AudioOutputOptions(
                track_name=track_name,
                track_publish_options=rtc.TrackPublishOptions(
                    source=track_source
                ),
            ),
        ),
    )
    logger.info(f"[{session_label}] AgentSession started, listening to: {source_participant.identity}, track: {track_name}")
    return session


async def entrypoint(ctx: JobContext):
    logger.info("Initializing BabelChef Translation Agent Worker")

    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)

    # Collect participants as they join using a future
    participants_ready = asyncio.Future()
    participants = {}

    def on_participant_connected(participant: rtc.RemoteParticipant):
        lang_code, lang_name = get_participant_language(participant)
        participants[participant.identity] = (participant, lang_code, lang_name)
        logger.info(f"Participant joined: {participant.identity} ({participant.name}) speaks {lang_name} ({lang_code})")
        logger.info(f"Total participants: {len(participants)}")

        if len(participants) >= 2 and not participants_ready.done():
            participants_ready.set_result(True)

    # Register the event handler
    ctx.room.on("participant_connected", on_participant_connected)

    # Check participants already in the room
    for p in ctx.room.remote_participants.values():
        on_participant_connected(p)

    if len(participants) < 2:
        logger.info(f"Waiting for 2 participants (currently {len(participants)})...")
        try:
            await asyncio.wait_for(participants_ready, timeout=300)  # 5 min timeout
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for 2 participants")
            return

    # Get the two participants
    items = list(participants.values())
    p1, code1, lang1 = items[0]
    p2, code2, lang2 = items[1]

    logger.info(f"Both participants present!")
    logger.info(f"  P1: {p1.identity} ({p1.name}) speaks {lang1} ({code1})")
    logger.info(f"  P2: {p2.identity} ({p2.name}) speaks {lang2} ({code2})")

    # Create two sessions with DIFFERENT track sources to avoid LiveKit deduplication:
    # Session 1: Listens to P1 (lang1) -> translates to lang2
    #   Audio track: "translation-{code2}" with SOURCE_MICROPHONE
    # Session 2: Listens to P2 (lang2) -> translates to lang1
    #   Audio track: "translation-{code1}" with SOURCE_SCREENSHARE_AUDIO (different source!)
    session1 = await create_session_for_participant(
        ctx, p1, lang1, code2, lang2,
        session_label=f"{lang1}->{lang2}",
        track_source=rtc.TrackSource.SOURCE_MICROPHONE,
    )

    session2 = await create_session_for_participant(
        ctx, p2, lang2, code1, lang1,
        session_label=f"{lang2}->{lang1}",
        track_source=rtc.TrackSource.SOURCE_SCREENSHARE_AUDIO,
    )

    logger.info(f"Both translation sessions active in room: {ctx.room.name}")
    logger.info(f"  {p1.name} ({lang1}): audio track = translation-{code2} (SOURCE_MICROPHONE)")
    logger.info(f"  {p2.name} ({lang2}): audio track = translation-{code1} (SOURCE_SCREENSHARE_AUDIO)")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            port=0,
            job_executor_type=JobExecutorType.THREAD,
            num_idle_processes=0,
        )
    )
