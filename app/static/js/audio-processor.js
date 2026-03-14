/**
 * BabelChef — Audio Processor
 *
 * Handles PCM audio recording from the microphone and playback of
 * received translated audio via the Web Audio API.
 */

class AudioProcessor {
    constructor() {
        this.audioContext = null;
        this.mediaStream = null;
        this.audioWorkletNode = null;
        this.isRecording = false;
        this.onAudioData = null; // Callback: (base64PcmData) => void

        // Playback queue
        this._playbackQueue = [];
        this._isPlaying = false;
    }

    /**
     * Initialize audio context and request mic permission.
     */
    async init() {
        this.audioContext = new AudioContext({ sampleRate: 16000 });

        // Request microphone access
        this.mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: 16000,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
            },
        });

        // Create a ScriptProcessorNode for capturing PCM (deprecated but widely supported)
        const source = this.audioContext.createMediaStreamSource(this.mediaStream);
        const processor = this.audioContext.createScriptProcessor(4096, 1, 1);

        processor.onaudioprocess = (event) => {
            if (!this.isRecording || !this.onAudioData) return;

            const inputData = event.inputBuffer.getChannelData(0);
            // Convert Float32 → Int16 PCM
            const pcmData = this._float32ToInt16(inputData);
            // Convert to base64
            const base64 = this._arrayBufferToBase64(pcmData.buffer);
            this.onAudioData(base64);
        };

        source.connect(processor);
        processor.connect(this.audioContext.destination);
    }

    /**
     * Start recording audio from the microphone.
     */
    startRecording() {
        if (this.audioContext?.state === 'suspended') {
            this.audioContext.resume();
        }
        this.isRecording = true;
    }

    /**
     * Stop recording audio.
     */
    stopRecording() {
        this.isRecording = false;
    }

    /**
     * Toggle mute state.
     */
    toggleMute() {
        this.isRecording = !this.isRecording;
        return !this.isRecording; // Returns true if now muted
    }

    /**
     * Play received PCM audio (base64-encoded Int16 PCM at 24000Hz).
     */
    playAudio(base64Data, mimeType = 'audio/pcm;rate=24000') {
        // Parse sample rate from mime type
        const rateMatch = mimeType.match(/rate=(\d+)/);
        const sampleRate = rateMatch ? parseInt(rateMatch[1]) : 24000;

        // Decode base64 → ArrayBuffer
        const binaryStr = atob(base64Data);
        const bytes = new Uint8Array(binaryStr.length);
        for (let i = 0; i < binaryStr.length; i++) {
            bytes[i] = binaryStr.charCodeAt(i);
        }

        // Convert Int16 → Float32
        const int16Array = new Int16Array(bytes.buffer);
        const float32Array = new Float32Array(int16Array.length);
        for (let i = 0; i < int16Array.length; i++) {
            float32Array[i] = int16Array[i] / 32768.0;
        }

        // Create audio buffer and play
        const playbackContext = this.audioContext || new AudioContext();
        const audioBuffer = playbackContext.createBuffer(1, float32Array.length, sampleRate);
        audioBuffer.getChannelData(0).set(float32Array);

        const source = playbackContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(playbackContext.destination);
        source.start();
    }

    /**
     * Convert Float32Array to Int16Array (PCM encoding).
     */
    _float32ToInt16(float32Array) {
        const int16Array = new Int16Array(float32Array.length);
        for (let i = 0; i < float32Array.length; i++) {
            const s = Math.max(-1, Math.min(1, float32Array[i]));
            int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        return int16Array;
    }

    /**
     * Convert ArrayBuffer to base64 string.
     */
    _arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }

    /**
     * Cleanup resources.
     */
    destroy() {
        this.stopRecording();
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(t => t.stop());
        }
        if (this.audioContext) {
            this.audioContext.close();
        }
    }
}

// Export globally
window.AudioProcessor = AudioProcessor;
