/* WavRecorder: full-quality microphone capture to a lossless WAV Blob.
 *
 * Quality choices (browser recording is often noticeably worse than a local
 * recording app; these are the usual culprits, all avoided here):
 *  - no lossy codec: MediaRecorder's webm/opus is never used. Raw PCM comes
 *    straight from an AudioWorklet (static/js/pcm-worklet.js);
 *  - no browser "voice processing": echoCancellation, noiseSuppression and
 *    autoGainControl are all off - they are tuned for calls and audibly
 *    damage non-speech sounds (exactly what the noise game records);
 *  - no resampling in the browser: the AudioContext runs at the microphone
 *    track's own sample rate (typically 48 kHz) and the WAV is written at
 *    that rate;
 *  - no quantisation: samples are stored as 32-bit float WAV.
 * Each model worker resamples server-side with a proper resampler to
 * whatever rate its model needs (see workers/audio_io.py).
 *
 *   const rec = new WavRecorder({ onLevel: (rms) => ... });
 *   await rec.open();              // asks for mic permission once
 *   rec.start();
 *   const blob = await rec.stop(); // audio/wav, float32, native rate
 *   const blob = await rec.recordFor(4, (secondsLeft) => ...);
 *
 * The microphone needs a secure context: http://localhost or https (the
 * Cloudflare tunnel) - a plain http://<lan-ip> page cannot record.
 */

(function () {
  "use strict";

  const CONSTRAINTS = {
    audio: {
      channelCount: { ideal: 1 },
      sampleRate: { ideal: 48000 },
      sampleSize: { ideal: 24 },
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
      // Chrome-specific legacy flags, ignored elsewhere.
      googEchoCancellation: false,
      googNoiseSuppression: false,
      googAutoGainControl: false,
      googHighpassFilter: false,
    },
  };

  class WavRecorder {
    constructor({ onLevel = null } = {}) {
      this.onLevel = onLevel;
      this.chunks = [];
      this.recording = false;
    }

    async open() {
      if (this.context) return;
      this.stream = await navigator.mediaDevices.getUserMedia(CONSTRAINTS);
      const settings = this.stream.getAudioTracks()[0].getSettings();
      // Match the track's rate so the browser does not resample behind our back.
      const options = settings.sampleRate ? { sampleRate: settings.sampleRate } : {};
      this.context = new (window.AudioContext || window.webkitAudioContext)(options);
      this.settings = settings;
      const workletUrl = document.querySelector('meta[name="pcm-worklet-url"]').content;
      await this.context.audioWorklet.addModule(workletUrl);
      this.source = this.context.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.context, "pcm-capture");
      this.node.port.onmessage = (event) => this.onSamples(event.data);
      this.source.connect(this.node);
      // The worklet must reach the destination to be pulled; it outputs silence.
      this.node.connect(this.context.destination);
    }

    get sampleRate() {
      return this.context ? this.context.sampleRate : null;
    }

    onSamples(samples) {
      if (this.onLevel) {
        let sum = 0;
        for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
        this.onLevel(Math.sqrt(sum / samples.length));
      }
      if (this.recording) this.chunks.push(samples);
    }

    start() {
      if (this.context.state === "suspended") this.context.resume();
      this.chunks = [];
      this.recording = true;
    }

    async stop() {
      this.recording = false;
      const pcm = concat(this.chunks);
      this.chunks = [];
      return encodeWavFloat32(pcm, this.context.sampleRate);
    }

    async recordFor(seconds, onTick = null) {
      this.start();
      const started = Date.now();
      await new Promise((resolve) => {
        const timer = setInterval(() => {
          const elapsed = (Date.now() - started) / 1000;
          if (onTick) onTick(Math.max(0, seconds - elapsed));
          if (elapsed >= seconds) {
            clearInterval(timer);
            resolve();
          }
        }, 50);
      });
      return this.stop();
    }

    close() {
      if (!this.context) return;
      this.stream.getTracks().forEach((track) => track.stop());
      this.context.close();
      this.context = null;
    }
  }

  function concat(chunks) {
    const length = chunks.reduce((n, c) => n + c.length, 0);
    const out = new Float32Array(length);
    let offset = 0;
    chunks.forEach((c) => { out.set(c, offset); offset += c.length; });
    return out;
  }

  /* WAVE_FORMAT_IEEE_FLOAT (format tag 3), mono, 32-bit. */
  function encodeWavFloat32(samples, sampleRate) {
    const bytesPerSample = 4;
    const dataBytes = samples.length * bytesPerSample;
    const buffer = new ArrayBuffer(44 + dataBytes);
    const view = new DataView(buffer);
    const writeString = (offset, text) => { for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i)); };
    writeString(0, "RIFF");
    view.setUint32(4, 36 + dataBytes, true);
    writeString(8, "WAVE");
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 3, true);                         // IEEE float
    view.setUint16(22, 1, true);                         // mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * bytesPerSample, true);
    view.setUint16(32, bytesPerSample, true);
    view.setUint16(34, 32, true);
    writeString(36, "data");
    view.setUint32(40, dataBytes, true);
    new Float32Array(buffer, 44).set(samples);
    return new Blob([buffer], { type: "audio/wav" });
  }

  window.WavRecorder = WavRecorder;
})();
