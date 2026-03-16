/**
 * BabelChef — Gold Standard Client
 * Features:
 *   1. LiveKit WebRTC for video
 *   2. ADK Bidi Streaming via WebSocket for translation (cross-wired)
 *   3. Video frame capture → ADK for visual context
 *   4. Cooking assistant insights (ingredient/technique/status badges)
 *   5. Smart dual-line subtitles (original + translation)
 */

/* global LivekitClient */

// ─── State ───
let room = null;
let translationWs = null;
let audioContext = null;
let audioWorkletNode = null;
let mediaStream = null;
let frameIntervalId = null;

const myLang = () => document.getElementById("select-language").value;
const myName = () => document.getElementById("input-name").value.trim();

let currentRoomId = "";
let targetLang = "";

// Track seen cooking insights to avoid duplicates
const seenInsights = new Set();
let subtitleClearTimer = null;

// ─── DOM refs ───
const setupScreen = document.getElementById("setup-screen");
const callScreen = document.getElementById("call-screen");
const logEl = document.getElementById("event-log");
const subtitleOriginal = document.getElementById("subtitle-original");
const subtitleTranslation = document.getElementById("subtitle-translation");
const cookingInsightsEl = document.getElementById("cooking-insights");

function log(msg) {
    const ts = new Date().toLocaleTimeString();
    if (logEl) logEl.innerHTML += `<div>[${ts}] ${msg}</div>`;
    console.log(`[BabelChef] ${msg}`);
}

// ─── Playback state (gapless audio scheduling) ───
let playbackCtx = null;
let nextPlayTime = 0;

// ==========================================================
// SETUP: Create / Join Room
// ==========================================================
document.getElementById("btn-create").addEventListener("click", async () => {
    if (!validateName()) return;
    const roomId = String(Math.floor(100000 + Math.random() * 900000));
    document.getElementById("display-room-id").textContent = roomId;
    document.getElementById("room-created").classList.remove("hidden");
    currentRoomId = roomId;
    await joinRoom(roomId, true); // true = show room code banner
});

document.getElementById("btn-join").addEventListener("click", async () => {
    if (!validateName()) return;
    const roomId = document.getElementById("input-room-id").value.trim();
    if (!roomId) {
        document.getElementById("input-room-id").classList.add("shake");
        setTimeout(() => document.getElementById("input-room-id").classList.remove("shake"), 400);
        return;
    }
    currentRoomId = roomId;
    await joinRoom(roomId);
});

document.getElementById("btn-copy")?.addEventListener("click", () => {
    navigator.clipboard.writeText(currentRoomId);
});

function validateName() {
    if (!myName()) {
        document.getElementById("input-name").classList.add("shake");
        setTimeout(() => document.getElementById("input-name").classList.remove("shake"), 400);
        return false;
    }
    return true;
}

// ==========================================================
// JOIN LiveKit Room (video only) + start translation WS
// ==========================================================
async function joinRoom(roomId, showCodeBanner = false) {
    const lang = myLang();
    const participantId = `${myName()} (${lang})`;
    log(`Joining room ${roomId} as ${participantId}...`);

    try {
        // Get LiveKit token
        const res = await fetch("/token", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                room_name: roomId,
                participant_name: participantId,
                language: lang,
            }),
        });
        const tokenData = await res.json();
        const token = tokenData.token;

        // Use LiveKit URL from server (avoids hardcoding)
        const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
        const livekitUrl =
            location.hostname === "localhost" || location.hostname === "127.0.0.1"
                ? `${wsProto}//${location.hostname}:7880`
                : tokenData.livekit_url;

        // Connect to LiveKit (video only)
        room = new LivekitClient.Room({
            adaptiveStream: true,
            dynacast: true,
        });

        room.on(LivekitClient.RoomEvent.TrackSubscribed, handleTrackSubscribed);
        room.on(LivekitClient.RoomEvent.TrackUnsubscribed, handleTrackUnsubscribed);
        room.on(LivekitClient.RoomEvent.ParticipantConnected, (p) => {
            log(`Participant connected: ${p.identity}`);
            // Hide room code banner when someone joins
            document.getElementById("room-code-banner")?.classList.add("hidden");
            setTimeout(() => startTranslationStream(roomId, participantId, lang), 1500);
        });

        await room.connect(livekitUrl, token);
        log("Connected to LiveKit (video)");

        // Switch to call screen FIRST (before camera permission dialog)
        setupScreen.classList.remove("active");
        callScreen.classList.add("active");

        // Wire up controls
        wireControls();

        // Show room code banner if this user created the room
        if (showCodeBanner) {
            const banner = document.getElementById("room-code-banner");
            document.getElementById("banner-room-code").textContent = roomId;
            banner.classList.remove("hidden");

            document.getElementById("btn-copy-banner").addEventListener("click", () => {
                navigator.clipboard.writeText(roomId);
                document.getElementById("btn-copy-banner").textContent = "✅";
                setTimeout(() => (document.getElementById("btn-copy-banner").textContent = "📋"), 1500);
            });
            document.getElementById("btn-dismiss-banner").addEventListener("click", () => {
                banner.classList.add("hidden");
            });
        }

        // NOW enable camera (permission dialog appears on call screen, not setup)
        try {
            await room.localParticipant.setCameraEnabled(true);
            const localVideo = document.getElementById("local-video");
            const camTrack = room.localParticipant.getTrackPublication(
                LivekitClient.Track.Source.Camera
            );
            if (camTrack?.track) {
                camTrack.track.attach(localVideo);
            }
        } catch (camErr) {
            log(`Camera error (continuing without): ${camErr.message}`);
        }

        // If the other participant is already in the room, start translation
        if (room.remoteParticipants.size > 0) {
            setTimeout(() => startTranslationStream(roomId, participantId, lang), 1500);
        }

    } catch (err) {
        log(`Join error: ${err.message || err}`);
        alert(`Failed to join: ${err.message || err}`);
    }
}

// ==========================================================
// VIDEO TRACK HANDLING (human participants only)
// ==========================================================
function handleTrackSubscribed(track, publication, participant) {
    if (track.kind !== "video") return;

    // Only show video from human participants (not agents)
    const meta = participant.metadata ? JSON.parse(participant.metadata) : {};
    if (meta.agent) return;

    log(`Video track from ${participant.identity}`);
    const container = document.getElementById("remote-video-container");
    const el = track.attach();
    el.id = "remote-video-el";
    container.insertBefore(el, container.firstChild);

    // Update remote name
    document.getElementById("remote-name").textContent = participant.identity;
}

function handleTrackUnsubscribed(track) {
    if (track.kind === "video") {
        track.detach().forEach((el) => el.remove());
    }
}

// ==========================================================
// TRANSLATION WEBSOCKET (ADK Bidi Streaming)
// ==========================================================
async function startTranslationStream(roomId, participantId, lang) {
    if (translationWs && translationWs.readyState === WebSocket.OPEN) return;

    // Discover the other participant's language
    try {
        const infoRes = await fetch(`/room-info/${roomId}`);
        const info = await infoRes.json();
        const others = Object.entries(info.participants).filter(
            ([name]) => name !== participantId
        );
        if (others.length > 0) {
            targetLang = others[0][1];
        } else {
            log("No other participant yet, waiting...");
            setTimeout(() => startTranslationStream(roomId, participantId, lang), 2000);
            return;
        }
    } catch (e) {
        log(`Room info error: ${e}`);
        return;
    }

    log(`Starting translation: ${lang} → ${targetLang}`);

    const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProto}//${location.host}/ws/translate/${roomId}/${encodeURIComponent(participantId)}?source_lang=${lang}&target_lang=${targetLang}`;

    translationWs = new WebSocket(wsUrl);

    translationWs.onopen = () => {
        log("Translation WebSocket connected");
        startAudioCapture();
        startVideoFrameCapture();
    };

    translationWs.onmessage = (event) => {
        if (event.data instanceof Blob) {
            // Binary = translated audio from the OTHER person
            event.data.arrayBuffer().then((buf) => playTranslatedAudio(buf));
        } else {
            // JSON message
            try {
                const msg = JSON.parse(event.data);
                console.log("[BabelChef] WS message:", msg.type, msg);
                if (msg.type === "transcription") {
                    showSubtitle(msg);
                } else if (msg.type === "input_transcription") {
                    // Built-in Gemini transcription of original speech
                    showOriginalSpeech(msg);
                } else if (msg.type === "output_transcription") {
                    // Built-in Gemini transcription of translated speech
                    showTranslatedSpeech(msg);
                } else if (msg.type === "cooking_insight") {
                    showCookingInsight(msg);
                }
            } catch (e) {
                // ignore
            }
        }
    };

    translationWs.onclose = () => {
        log("Translation WebSocket closed");
        stopAudioCapture();
        stopVideoFrameCapture();
    };

    translationWs.onerror = (e) => {
        log(`Translation WebSocket error: ${e}`);
    };
}

// ==========================================================
// AUDIO CAPTURE (PCM 16kHz via AudioWorklet)
// ==========================================================
async function startAudioCapture() {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: 16000,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
            },
        });

        audioContext = new AudioContext({ sampleRate: 16000 });
        await audioContext.audioWorklet.addModule("/static/js/pcm-capture-processor.js");

        const source = audioContext.createMediaStreamSource(mediaStream);
        audioWorkletNode = new AudioWorkletNode(audioContext, "pcm-capture-processor");

        audioWorkletNode.port.onmessage = (event) => {
            if (
                translationWs &&
                translationWs.readyState === WebSocket.OPEN &&
                event.data instanceof ArrayBuffer
            ) {
                translationWs.send(event.data);
            }
        };

        source.connect(audioWorkletNode);
        audioWorkletNode.connect(audioContext.destination); // needed to keep processing
        log("Audio capture started (PCM 16kHz)");
    } catch (e) {
        log(`Audio capture error: ${e}`);
    }
}

function stopAudioCapture() {
    if (audioWorkletNode) {
        audioWorkletNode.disconnect();
        audioWorkletNode = null;
    }
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    if (mediaStream) {
        mediaStream.getTracks().forEach((t) => t.stop());
        mediaStream = null;
    }
}

// ==========================================================
// AUDIO PLAYBACK (PCM 24kHz gapless)
// ==========================================================
function playTranslatedAudio(arrayBuffer) {
    if (!playbackCtx) {
        playbackCtx = new AudioContext({ sampleRate: 24000 });
        nextPlayTime = playbackCtx.currentTime;
    }

    const int16 = new Int16Array(arrayBuffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768;
    }

    const buffer = playbackCtx.createBuffer(1, float32.length, 24000);
    buffer.copyToChannel(float32, 0);

    const source = playbackCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(playbackCtx.destination);

    const now = playbackCtx.currentTime;
    if (nextPlayTime < now) nextPlayTime = now;
    source.start(nextPlayTime);
    nextPlayTime += buffer.duration;
}

// ==========================================================
// VIDEO FRAME CAPTURE (JPEG 768×768 every 2s → WebSocket)
// ==========================================================
function startVideoFrameCapture() {
    const canvas = document.getElementById("frame-canvas");
    const ctx = canvas.getContext("2d");

    frameIntervalId = setInterval(() => {
        // Find the remote video element
        const videoEl = document.getElementById("remote-video-el");
        if (
            !videoEl ||
            !videoEl.videoWidth ||
            translationWs?.readyState !== WebSocket.OPEN
        ) {
            return;
        }

        // Draw video frame to 768×768 canvas
        canvas.width = 768;
        canvas.height = 768;

        // Maintain aspect ratio with center crop
        const vw = videoEl.videoWidth;
        const vh = videoEl.videoHeight;
        const scale = Math.max(768 / vw, 768 / vh);
        const sw = 768 / scale;
        const sh = 768 / scale;
        const sx = (vw - sw) / 2;
        const sy = (vh - sh) / 2;

        ctx.drawImage(videoEl, sx, sy, sw, sh, 0, 0, 768, 768);

        // Export as JPEG, then send as base64 JSON
        canvas.toBlob(
            (blob) => {
                if (!blob) return;
                const reader = new FileReader();
                reader.onloadend = () => {
                    // reader.result is "data:image/jpeg;base64,..."
                    const base64 = reader.result.split(",")[1];
                    if (translationWs?.readyState === WebSocket.OPEN) {
                        translationWs.send(
                            JSON.stringify({
                                type: "image",
                                data: base64,
                                mimeType: "image/jpeg",
                            })
                        );
                    }
                };
                reader.readAsDataURL(blob);
            },
            "image/jpeg",
            0.7 // quality — balance size vs detail
        );
    }, 2000); // Every 2 seconds

    log("Video frame capture started (768×768 JPEG, 0.5 FPS)");
}

function stopVideoFrameCapture() {
    if (frameIntervalId) {
        clearInterval(frameIntervalId);
        frameIntervalId = null;
    }
}

// ==========================================================
// SMART SUBTITLES — dual line (original + translation)
// ==========================================================
function showSubtitle(msg) {
    const { text, source_lang, target_lang } = msg;
    if (!text || !text.trim()) return;

    // Determine if this is original speech or translation
    // If source_lang matches MY language, this is the translation of the OTHER person's speech
    // I should see it as the translation line
    const myLanguage = myLang();

    if (target_lang === myLanguage) {
        // This is a translation INTO my language — show as translation
        subtitleTranslation.textContent = text;
    } else {
        // This is a translation FROM my language — show as original
        subtitleOriginal.textContent = text;
    }

    // Auto-clear after 6 seconds
    clearTimeout(subtitleClearTimer);
    subtitleClearTimer = setTimeout(() => {
        subtitleOriginal.textContent = "";
        subtitleTranslation.textContent = "";
    }, 6000);
}

// Built-in Gemini transcription of ORIGINAL speech (input_transcription)
function showOriginalSpeech(msg) {
    const { text, source_lang } = msg;
    if (!text || !text.trim()) return;

    // Input transcription = what was spoken in source language
    // If source_lang matches MY language, this is MY speech → show as original
    // If source_lang is OTHER person's language, this is THEIR speech → also original
    subtitleOriginal.textContent = text;

    clearTimeout(subtitleClearTimer);
    subtitleClearTimer = setTimeout(() => {
        subtitleOriginal.textContent = "";
        subtitleTranslation.textContent = "";
    }, 6000);
}

// Built-in Gemini transcription of TRANSLATED speech (output_transcription)
function showTranslatedSpeech(msg) {
    const { text } = msg;
    if (!text || !text.trim()) return;

    // Output transcription = the translated audio that Gemini produced
    subtitleTranslation.textContent = text;

    clearTimeout(subtitleClearTimer);
    subtitleClearTimer = setTimeout(() => {
        subtitleOriginal.textContent = "";
        subtitleTranslation.textContent = "";
    }, 6000);
}

// ==========================================================
// COOKING INSIGHTS — animated badges
// ==========================================================
function showCookingInsight(msg) {
    const { label, category } = msg;
    if (!label) return;

    // Deduplicate
    const key = label.toLowerCase().trim();
    if (seenInsights.has(key)) return;
    seenInsights.add(key);

    // Limit to 6 visible badges
    const badges = cookingInsightsEl.querySelectorAll(".insight-badge:not(.fading)");
    if (badges.length >= 6) {
        // Remove the oldest
        const oldest = badges[0];
        oldest.classList.add("fading");
        setTimeout(() => oldest.remove(), 500);
    }

    // Create badge
    const badge = document.createElement("div");
    badge.className = `insight-badge ${category || "ingredient"}`;
    badge.textContent = label;
    cookingInsightsEl.appendChild(badge);

    log(`🍳 Insight: [${category}] ${label}`);

    // Auto-fade after 12 seconds
    setTimeout(() => {
        badge.classList.add("fading");
        setTimeout(() => {
            badge.remove();
            seenInsights.delete(key);
        }, 500);
    }, 12000);
}

// ==========================================================
// CALL CONTROLS
// ==========================================================
function wireControls() {
    // Mute toggle (mic via AudioWorklet, not LiveKit)
    let micMuted = false;
    document.getElementById("btn-mute").addEventListener("click", () => {
        const btn = document.getElementById("btn-mute");
        micMuted = !micMuted;

        // Pause/resume the audio worklet mic stream
        if (mediaStream) {
            mediaStream.getAudioTracks().forEach((t) => (t.enabled = !micMuted));
        }

        if (micMuted) {
            btn.classList.add("muted");
            btn.querySelector(".icon").textContent = "🔇";
        } else {
            btn.classList.remove("muted");
            btn.querySelector(".icon").textContent = "🎤";
        }
    });

    // Camera toggle
    document.getElementById("btn-camera").addEventListener("click", async () => {
        const camPub = room.localParticipant.getTrackPublication(
            LivekitClient.Track.Source.Camera
        );
        if (camPub?.isMuted) {
            camPub.unmute();
        } else if (camPub) {
            camPub.mute();
        }
    });

    // Flip camera — use restartTrack with new facingMode
    let currentFacing = "user";
    document.getElementById("btn-flip").addEventListener("click", async () => {
        try {
            currentFacing = currentFacing === "user" ? "environment" : "user";
            log(`Flipping camera to: ${currentFacing}`);

            const camPub = room.localParticipant.getTrackPublication(
                LivekitClient.Track.Source.Camera
            );
            if (camPub?.track) {
                await camPub.track.restartTrack({
                    facingMode: currentFacing,
                });
                camPub.track.attach(document.getElementById("local-video"));
            }
        } catch (flipErr) {
            log(`Flip camera error: ${flipErr.message}`);
        }
    });

    // End call
    document.getElementById("btn-end").addEventListener("click", () => {
        if (translationWs) translationWs.close();
        stopAudioCapture();
        stopVideoFrameCapture();
        if (room) room.disconnect();
        callScreen.classList.remove("active");
        setupScreen.classList.add("active");
    });
}
