"""Room Manager — manages call rooms with two participants.

Each room maintains:
  - Two WebSocket connections (one per participant)
  - Two ADK translation pipelines (EN→HI, HI→EN)
  - Video frame relay between participants
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from google.adk.agents import LiveRequestQueue
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService, Session
from google.adk.agents.run_config import RunConfig
from google.genai import types

from app.agents.translator_agent import en_to_hi_agent, hi_to_en_agent

logger = logging.getLogger(__name__)


class ParticipantRole(str, Enum):
    """Identifies which side of the call a participant is on."""
    ENGLISH_SPEAKER = "english"   # The wife
    HINDI_SPEAKER = "hindi"       # The mom


@dataclass
class Participant:
    """A single participant in a call room."""
    participant_id: str
    role: ParticipantRole
    websocket: Any = None  # FastAPI WebSocket


@dataclass
class TranslationPipeline:
    """One direction of the translation (e.g., EN→HI)."""
    runner: Runner
    session: Session | None = None
    live_queue: LiveRequestQueue | None = None
    run_config: RunConfig | None = None


@dataclass
class Room:
    """A call room between two participants with bidirectional translation."""
    room_id: str
    participants: dict[str, Participant] = field(default_factory=dict)
    en_to_hi_pipeline: TranslationPipeline | None = None
    hi_to_en_pipeline: TranslationPipeline | None = None
    ready_event: asyncio.Event = field(default_factory=asyncio.Event)
    _created_at: float = field(default_factory=lambda: __import__("time").time())

    @property
    def is_full(self) -> bool:
        return len(self.participants) >= 2

    @property
    def english_speaker(self) -> Participant | None:
        for p in self.participants.values():
            if p.role == ParticipantRole.ENGLISH_SPEAKER:
                return p
        return None

    @property
    def hindi_speaker(self) -> Participant | None:
        for p in self.participants.values():
            if p.role == ParticipantRole.HINDI_SPEAKER:
                return p
        return None

    def other_participant(self, participant_id: str) -> Participant | None:
        """Get the other participant in the room."""
        for pid, p in self.participants.items():
            if pid != participant_id:
                return p
        return None


class RoomManager:
    """Manages active call rooms."""

    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._session_service = InMemorySessionService()

        # Create runners for each translation direction
        self._en_to_hi_runner = Runner(
            app_name="babelchef-en-hi",
            agent=en_to_hi_agent,
            session_service=self._session_service,
        )
        self._hi_to_en_runner = Runner(
            app_name="babelchef-hi-en",
            agent=hi_to_en_agent,
            session_service=self._session_service,
        )

    async def create_room(self) -> Room:
        """Create a new call room."""
        room_id = str(uuid.uuid4())[:8]
        room = Room(room_id=room_id)
        self._rooms[room_id] = room
        logger.info("Room %s created", room_id)
        return room

    def get_room(self, room_id: str) -> Room | None:
        return self._rooms.get(room_id)

    async def join_room(
        self,
        room_id: str,
        participant_id: str,
        role: ParticipantRole,
        websocket: Any,
    ) -> Room:
        """Add a participant to a room and initialize their translation pipeline."""
        room = self._rooms.get(room_id)
        if room is None:
            raise ValueError(f"Room {room_id} does not exist")
        if room.is_full:
            raise ValueError(f"Room {room_id} is already full")

        participant = Participant(
            participant_id=participant_id,
            role=role,
            websocket=websocket,
        )
        room.participants[participant_id] = participant

        # Initialize translation pipelines when both participants join
        if room.is_full:
            await self._init_pipelines(room)
            room.ready_event.set()  # Signal waiting participants

        logger.info(
            "Participant %s joined room %s as %s",
            participant_id, room_id, role.value,
        )
        return room

    async def _init_pipelines(self, room: Room) -> None:
        """Initialize the two Gemini Live API translation pipelines."""

        # EN→HI: translates wife's English speech to Hindi for mom
        en_hi_session = await self._session_service.create_session(
            app_name="babelchef-en-hi",
            user_id=f"room-{room.room_id}",
        )
        en_hi_queue = LiveRequestQueue()
        en_hi_config = RunConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Kore",  # A voice that works well for Hindi
                    )
                )
            ),
        )
        room.en_to_hi_pipeline = TranslationPipeline(
            runner=self._en_to_hi_runner,
            session=en_hi_session,
            live_queue=en_hi_queue,
            run_config=en_hi_config,
        )

        # HI→EN: translates mom's Hindi speech to English for wife
        hi_en_session = await self._session_service.create_session(
            app_name="babelchef-hi-en",
            user_id=f"room-{room.room_id}",
        )
        hi_en_queue = LiveRequestQueue()
        hi_en_config = RunConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede",  # English voice
                    )
                )
            ),
        )
        room.hi_to_en_pipeline = TranslationPipeline(
            runner=self._hi_to_en_runner,
            session=hi_en_session,
            live_queue=hi_en_queue,
            run_config=hi_en_config,
        )
        logger.info("Translation pipelines initialized for room %s", room.room_id)

    async def leave_room(self, room_id: str, participant_id: str) -> None:
        """Remove a participant and clean up their pipeline."""
        room = self._rooms.get(room_id)
        if room is None:
            return

        if participant_id in room.participants:
            del room.participants[participant_id]

        # Close queues if room is empty
        if not room.participants:
            if room.en_to_hi_pipeline and room.en_to_hi_pipeline.live_queue:
                room.en_to_hi_pipeline.live_queue.close()
            if room.hi_to_en_pipeline and room.hi_to_en_pipeline.live_queue:
                room.hi_to_en_pipeline.live_queue.close()
            del self._rooms[room_id]
            logger.info("Room %s destroyed", room_id)
        else:
            logger.info("Participant %s left room %s", participant_id, room_id)

    def list_rooms(self) -> list[dict]:
        """List all active rooms."""
        return [
            {
                "room_id": r.room_id,
                "participants": len(r.participants),
                "is_full": r.is_full,
            }
            for r in self._rooms.values()
        ]
