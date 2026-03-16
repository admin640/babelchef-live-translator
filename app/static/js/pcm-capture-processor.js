/**
 * AudioWorklet processor for capturing PCM 16-bit audio.
 * Converts Float32 samples from the Web Audio API to Int16 PCM bytes,
 * then posts them to the main thread for WebSocket transmission.
 */
class PcmCaptureProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this._buffer = new Int16Array(0);
        // Send chunks of ~100ms at 16kHz = 1600 samples = 3200 bytes
        this._chunkSize = 1600;
    }

    process(inputs) {
        const input = inputs[0];
        if (!input || !input[0]) return true;

        const float32Data = input[0]; // mono channel
        const int16Data = new Int16Array(float32Data.length);

        // Convert Float32 [-1, 1] to Int16 [-32768, 32767]
        for (let i = 0; i < float32Data.length; i++) {
            const s = Math.max(-1, Math.min(1, float32Data[i]));
            int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }

        // Append to buffer
        const combined = new Int16Array(this._buffer.length + int16Data.length);
        combined.set(this._buffer);
        combined.set(int16Data, this._buffer.length);
        this._buffer = combined;

        // Send complete chunks
        while (this._buffer.length >= this._chunkSize) {
            const chunk = this._buffer.slice(0, this._chunkSize);
            this._buffer = this._buffer.slice(this._chunkSize);
            this.port.postMessage(chunk.buffer, [chunk.buffer]);
        }

        return true;
    }
}

registerProcessor('pcm-capture-processor', PcmCaptureProcessor);
