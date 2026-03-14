/**
 * BabelChef — Main Application Logic
 *
 * Handles room creation/joining, WebSocket communication,
 * camera capture, and translated audio/video rendering.
 */

// ── State ───────────────────────────────────────────────────────────────

let ws = null;
let audioProcessor = null;
let localStream = null;
let videoInterval = null;
let currentRole = 'english';
let currentRoomId = null;
let isMuted = false;
let isCameraOn = true;
let subtitleTimeout = null;

// ── DOM Elements ────────────────────────────────────────────────────────

const setupScreen = document.getElementById('setup-screen');
const callScreen = document.getElementById('call-screen');
const btnCreate = document.getElementById('btn-create');
const btnJoin = document.getElementById('btn-join');
const inputRoomId = document.getElementById('input-room-id');
const roomCreatedDiv = document.getElementById('room-created');
const displayRoomId = document.getElementById('display-room-id');
const localVideo = document.getElementById('local-video');
const remoteCanvas = document.getElementById('remote-canvas');
const subtitleText = document.getElementById('subtitle-text');
const remoteLabel = document.getElementById('remote-label');
const localLabel = document.getElementById('local-label');
const btnMute = document.getElementById('btn-mute');
const btnCamera = document.getElementById('btn-camera');
const btnEnd = document.getElementById('btn-end');
const eventLog = document.getElementById('event-log');

// ── Helpers ─────────────────────────────────────────────────────────────

function getSelectedRole() {
    return document.querySelector('input[name="role"]:checked').value;
}

function log(msg, type = 'info') {
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    entry.style.color = type === 'error' ? '#ef4444' : type === 'success' ? '#10b981' : '#9ca3af';
    eventLog.prepend(entry);
    console.log(`[BabelChef] ${msg}`);
}

function showSubtitle(text) {
    subtitleText.textContent = text;
    subtitleText.classList.add('visible');
    if (subtitleTimeout) clearTimeout(subtitleTimeout);
    subtitleTimeout = setTimeout(() => {
        subtitleText.classList.remove('visible');
    }, 5000);
}

function switchToCallScreen() {
    setupScreen.classList.remove('active');
    callScreen.classList.add('active');

    // Update labels based on role
    if (currentRole === 'english') {
        localLabel.innerHTML = '<span class="flag-badge">🇺🇸</span> You (English)';
        remoteLabel.innerHTML = '<span class="flag-badge">🇮🇳</span> Other (Hindi)';
    } else {
        localLabel.innerHTML = '<span class="flag-badge">🇮🇳</span> You (Hindi)';
        remoteLabel.innerHTML = '<span class="flag-badge">🇺🇸</span> Other (English)';
    }
}

// ── Camera ──────────────────────────────────────────────────────────────

async function startCamera() {
    try {
        localStream = await navigator.mediaDevices.getUserMedia({
            video: { width: 640, height: 480, facingMode: 'environment' },
            audio: false, // Audio handled separately by AudioProcessor
        });
        localVideo.srcObject = localStream;
        log('Camera started', 'success');
    } catch (err) {
        log(`Camera error: ${err.message}`, 'error');
    }
}

function captureVideoFrame() {
    if (!localStream || !isCameraOn) return null;

    const video = localVideo;
    if (video.videoWidth === 0) return null;

    const canvas = document.createElement('canvas');
    canvas.width = 320;  // Downscale for bandwidth
    canvas.height = 240;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    // Convert to JPEG base64
    const dataUrl = canvas.toDataURL('image/jpeg', 0.5);
    return dataUrl.split(',')[1]; // Remove "data:image/jpeg;base64," prefix
}

function startVideoCapture() {
    // Send video frames every 500ms (2fps — enough for cooking context)
    videoInterval = setInterval(() => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        const frame = captureVideoFrame();
        if (frame) {
            ws.send(JSON.stringify({ type: 'video', data: frame }));
        }
    }, 500);
}

function stopVideoCapture() {
    if (videoInterval) {
        clearInterval(videoInterval);
        videoInterval = null;
    }
}

// ── Display remote video frames ─────────────────────────────────────────

function displayRemoteFrame(base64Data) {
    const canvas = remoteCanvas;
    const ctx = canvas.getContext('2d');
    const img = new Image();

    img.onload = () => {
        canvas.width = img.width;
        canvas.height = img.height;
        ctx.drawImage(img, 0, 0);
    };
    img.src = 'data:image/jpeg;base64,' + base64Data;

    // Show canvas, hide video element (since we're using canvas for remote)
    canvas.style.display = 'block';
}

// ── WebSocket ───────────────────────────────────────────────────────────

function connectWebSocket(roomId, role) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${roomId}/${role}`;

    log(`Connecting to ${wsUrl}...`);
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        log('WebSocket connected', 'success');
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleMessage(msg);
        } catch (e) {
            log(`Parse error: ${e.message}`, 'error');
        }
    };

    ws.onerror = (event) => {
        log('WebSocket error', 'error');
    };

    ws.onclose = (event) => {
        log(`WebSocket closed (code: ${event.code})`, 'error');
        stopVideoCapture();
    };
}

async function handleMessage(msg) {
    switch (msg.type) {
        case 'joined':
            log(`Joined room ${msg.room_id} as ${msg.role}`, 'success');
            break;

        case 'waiting':
            log(msg.message);
            break;

        case 'call_started':
            log(msg.message, 'success');
            switchToCallScreen();
            await startCamera();
            startVideoCapture();

            // Initialize and start audio
            audioProcessor = new AudioProcessor();
            await audioProcessor.init();
            audioProcessor.onAudioData = (base64Data) => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'audio', data: base64Data }));
                }
            };
            audioProcessor.startRecording();
            log('Audio recording started', 'success');
            break;

        case 'audio':
            // Play translated audio
            if (audioProcessor) {
                audioProcessor.playAudio(msg.data, msg.mime_type || 'audio/pcm;rate=24000');
            }
            break;

        case 'video':
            // Display remote video frame
            displayRemoteFrame(msg.data);
            break;

        case 'subtitle':
            showSubtitle(msg.text);
            break;

        case 'control':
            if (msg.action === 'participant_left') {
                log('Other participant left the call', 'error');
                showSubtitle('Call ended — other participant left');
            }
            break;

        case 'event':
            log(`Server event: ${msg.data}`);
            break;

        case 'error':
            log(`Error: ${msg.error}`, 'error');
            break;

        default:
            log(`Unknown message type: ${msg.type}`);
    }
}

// ── Room Actions ────────────────────────────────────────────────────────

btnCreate.addEventListener('click', async () => {
    currentRole = getSelectedRole();

    try {
        const res = await fetch('/rooms', { method: 'POST' });
        const data = await res.json();
        currentRoomId = data.room_id;

        displayRoomId.textContent = currentRoomId;
        roomCreatedDiv.classList.remove('hidden');
        btnCreate.disabled = true;
        btnCreate.textContent = 'Room Created';

        log(`Room created: ${currentRoomId}`, 'success');

        // Auto-connect via WebSocket
        connectWebSocket(currentRoomId, currentRole);
    } catch (err) {
        log(`Failed to create room: ${err.message}`, 'error');
    }
});

btnJoin.addEventListener('click', () => {
    const roomId = inputRoomId.value.trim();
    if (!roomId) {
        inputRoomId.focus();
        return;
    }

    currentRole = getSelectedRole();
    currentRoomId = roomId;

    log(`Joining room ${roomId} as ${currentRole}...`);
    connectWebSocket(roomId, currentRole);
});

// ── Call Controls ───────────────────────────────────────────────────────

btnMute.addEventListener('click', () => {
    if (audioProcessor) {
        isMuted = audioProcessor.toggleMute();
        btnMute.classList.toggle('muted', isMuted);
        btnMute.querySelector('.icon').textContent = isMuted ? '🔇' : '🎤';
        log(isMuted ? 'Muted' : 'Unmuted');
    }
});

btnCamera.addEventListener('click', () => {
    isCameraOn = !isCameraOn;
    if (localStream) {
        localStream.getVideoTracks().forEach(t => { t.enabled = isCameraOn; });
    }
    btnCamera.querySelector('.icon').textContent = isCameraOn ? '📷' : '🚫';
    log(isCameraOn ? 'Camera on' : 'Camera off');
});

btnEnd.addEventListener('click', () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'control', action: 'end_call' }));
        ws.close();
    }
    stopVideoCapture();
    if (audioProcessor) audioProcessor.destroy();
    if (localStream) localStream.getTracks().forEach(t => t.stop());

    // Return to setup
    callScreen.classList.remove('active');
    setupScreen.classList.add('active');
    roomCreatedDiv.classList.add('hidden');
    btnCreate.disabled = false;
    btnCreate.innerHTML = '<span>📞</span> Create New Room';
    log('Call ended');
});

// ── Handle Enter key in room ID input ───────────────────────────────────

inputRoomId.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') btnJoin.click();
});
