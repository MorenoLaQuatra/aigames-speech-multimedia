/* SoundTrainer: in-browser transfer learning with TensorFlow.js speech-commands
 * (same approach as Teachable Machine's audio projects).
 *
 * The pretrained base model (18-word speech-commands, vendored under
 * static/vendor/speech-commands-0.5.4/model-18w) turns 1 s of audio into an
 * embedding; a tiny new head is trained on the team's own command words:
 *   "_background_noise_" + left / right / jump.
 *
 * Examples are recorded push-to-talk by SpectrogramCapture below (press, say
 * the word, release), not by the library's collectExample(), which can only
 * record a duration fixed in advance. The capture computes exactly the
 * library's features (44.1 kHz, FFT 1024, 232 frequency columns, analyser
 * smoothing 0) and adds them to the transfer dataset - the same two calls
 * collectExample() makes internally (dataset.addExample, collateTransferWords).
 *
 * Microphone: browser "voice processing" (echo cancellation, noise
 * suppression, automatic gain) is turned off - it is tuned for calls and
 * changes the sound between one example and the next.
 */

(function () {
  "use strict";

  const BACKGROUND = "_background_noise_";
  const COMMANDS = ["left", "right", "jump"];
  const AUDIO_CONSTRAINTS = { echoCancellation: false, noiseSuppression: false, autoGainControl: false };
  // The library's feature extraction (BrowserFftFeatureExtractor defaults).
  const SAMPLE_RATE = 44100;
  const FFT_SIZE = 1024;
  // Spectrogram values are dB (getFloatFrequencyData); map this range to a 0-1 level meter.
  const LEVEL_FLOOR_DB = -100;
  const LEVEL_CEIL_DB = -30;
  const SILENCE_DB = -160;
  // Audio kept from just before the button press, so a word started a
  // moment early is not clipped.
  const PRE_ROLL_SECONDS = 0.3;
  // Trimming: a frame is "voice" when it is this many dB above the quietest
  // frames of the recording; this much context is kept around the voice.
  const VOICE_ABOVE_FLOOR_DB = 8;
  const TRIM_PAD_SECONDS = 0.15;
  // Training: window hop as a fraction of the 1 s window, and batch size
  // (both the library's transfer.train() defaults).
  const WINDOW_HOP_RATIO = 0.25;
  const BATCH_SIZE = 32;
  // Windows run through the base model per step before yielding to the page.
  const EMBED_CHUNK = 4;

  let transferCounter = 0;

  function absoluteUrl(path) {
    return new URL(path, window.location.href).href;
  }

  function frameMeanDb(frame) {
    let sum = 0;
    for (let i = 0; i < frame.length; i++) sum += frame[i];
    return sum / frame.length;
  }

  /* Push-to-talk spectrogram recorder. One open microphone, frames computed
   * continuously (a short ring buffer is the pre-roll); start() / stop()
   * mark one example. */
  class SpectrogramCapture {
    constructor(frameSize, onLevel) {
      this.frameSize = frameSize;           // frequency columns kept (232)
      this.onLevel = onLevel;
      this.frameSeconds = FFT_SIZE / SAMPLE_RATE;
      this.preRollFrames = Math.round(PRE_ROLL_SECONDS / this.frameSeconds);
      this.ring = [];
      this.frames = null;                   // non-null while recording
    }

    get isOpen() {
      return Boolean(this.context);
    }

    async open() {
      if (this.context) return;
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: AUDIO_CONSTRAINTS, video: false });
      this.context = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: SAMPLE_RATE });
      if (this.context.state === "suspended") await this.context.resume();
      const source = this.context.createMediaStreamSource(this.stream);
      this.analyser = this.context.createAnalyser();
      this.analyser.fftSize = FFT_SIZE * 2;
      this.analyser.smoothingTimeConstant = 0;
      source.connect(this.analyser);
      this.buffer = new Float32Array(FFT_SIZE);
      this.timer = setInterval(() => this.onFrame(), this.frameSeconds * 1000);
    }

    onFrame() {
      this.analyser.getFloatFrequencyData(this.buffer);
      // Exact digital silence (muted mic, some USB devices) reads -Infinity
      // dB; a finite floor keeps the frame (timing) and the maths finite.
      const frame = this.buffer.slice(0, this.frameSize);
      for (let i = 0; i < frame.length; i++) if (frame[i] < SILENCE_DB) frame[i] = SILENCE_DB;
      if (this.onLevel) {
        const db = frameMeanDb(frame);
        this.onLevel(Math.max(0, Math.min(1, (db - LEVEL_FLOOR_DB) / (LEVEL_CEIL_DB - LEVEL_FLOOR_DB))));
      }
      if (this.frames) {
        this.frames.push(frame);
      } else {
        this.ring.push(frame);
        if (this.ring.length > this.preRollFrames) this.ring.shift();
      }
    }

    start() {
      this.frames = this.ring.slice();
      this.ring = [];
    }

    /* Ends the example once at least minFrames were captured; returns the frames. */
    async stop(minFrames) {
      while (this.frames.length < minFrames) {
        await new Promise((resolve) => setTimeout(resolve, this.frameSeconds * 1000));
      }
      const frames = this.frames;
      this.frames = null;
      return frames;
    }

    async recordFor(seconds) {
      this.start();
      return this.stop(Math.ceil(seconds / this.frameSeconds));
    }

    close() {
      if (!this.context) return;
      clearInterval(this.timer);
      this.stream.getTracks().forEach((track) => track.stop());
      this.context.close();
      this.context = null;
      this.frames = null;
      this.ring = [];
    }
  }

  /* Keeps the part of a push-to-talk recording around the voice:
   * at least minFrames (the model's 1 s window), at most maxFrames. */
  function trimToVoice(frames, minFrames, maxFrames, padFrames) {
    const energy = frames.map(frameMeanDb);
    const sorted = energy.slice().sort((a, b) => a - b);
    const floor = sorted[Math.floor(sorted.length * 0.1)];
    let first = energy.findIndex((e) => e > floor + VOICE_ABOVE_FLOOR_DB);
    let last = energy.length - 1 - energy.slice().reverse().findIndex((e) => e > floor + VOICE_ABOVE_FLOOR_DB);
    if (first === -1) {
      // Nothing louder than the room: keep the middle of the recording.
      first = 0;
      last = energy.length - 1;
    }
    let begin = Math.max(0, first - padFrames);
    let end = Math.min(frames.length, last + 1 + padFrames);
    if (end - begin > maxFrames) end = begin + maxFrames;
    // Grow symmetrically around the voice up to the 1 s window.
    while (end - begin < minFrames) {
      if (begin > 0) begin -= 1;
      if (end - begin < minFrames && end < frames.length) end += 1;
    }
    return frames.slice(begin, end);
  }

  class SoundTrainer {
    constructor(settings, urls) {
      this.settings = settings;
      this.urls = urls;
      this.base = null;
      this.transfer = null;
      this.capture = null;
      // word -> [{uid, frames}] (frames: one Float32Array per spectrogram frame)
      this.examples = { [BACKGROUND]: [], left: [], right: [], jump: [] };
      this.trained = false;
      this.busy = false;
      this.levelListener = null;
    }

    async loadBase() {
      if (this.base) return;
      // speech-commands only accepts absolute http(s) URLs for metadata.
      const recognizer = speechCommands.create(
        "BROWSER_FFT", undefined, absoluteUrl(this.urls.modelJson), absoluteUrl(this.urls.metadataJson));
      await recognizer.ensureModelLoaded();
      this.base = recognizer;
      const [, numFrames, frameSize] = recognizer.modelInputShape();
      this.numFrames = numFrames;            // 43 frames = 1 s
      this.frameSize = frameSize;            // 232 columns
      await this.reset();
    }

    /* Start over with a fresh, untrained head (new team, or "redo all"). */
    async reset() {
      await this.stopListening();
      transferCounter += 1;
      this.transfer = this.base.createTransfer(`team-model-${transferCounter}`);
      this.examples = { [BACKGROUND]: [], left: [], right: [], jump: [] };
      this.trained = false;
    }

    target(word) {
      return word === BACKGROUND ? 1 : this.settings.examplesPerCommand;
    }

    count(word) {
      return this.examples[word].length;
    }

    hasAnyExample() {
      return Object.values(this.examples).some((list) => list.length > 0);
    }

    isComplete() {
      return Object.keys(this.examples).every((word) => this.count(word) >= this.target(word));
    }

    /* Opens the microphone for push-to-talk (idempotent). onLevel(0..1). */
    async openMic(onLevel) {
      this.levelListener = onLevel;
      if (!this.capture) this.capture = new SpectrogramCapture(this.frameSize, (level) => {
        if (this.levelListener) this.levelListener(level);
      });
      await this.capture.open();
    }

    closeMic() {
      if (this.capture) this.capture.close();
    }

    /* Push-to-talk: pressStart() on press, pressEnd(word) on release. */
    pressStart() {
      this.capture.start();
    }

    /* Returns the new example {uid, frames}. */
    async pressEnd(word) {
      const frameSeconds = this.capture.frameSeconds;
      const frames = await this.capture.stop(this.numFrames);
      const kept = trimToVoice(frames, this.numFrames,
        Math.round(this.settings.maxExampleSeconds / frameSeconds), Math.round(TRIM_PAD_SECONDS / frameSeconds));
      return this.addExample(word, kept);
    }

    /* Background noise: one long recording of the room (replaces any previous one). */
    async recordBackground(seconds) {
      const frames = await this.capture.recordFor(seconds);
      this.clearWord(BACKGROUND);
      return this.addExample(BACKGROUND, frames);
    }

    addExample(word, frames) {
      const data = new Float32Array(frames.length * this.frameSize);
      frames.forEach((frame, i) => data.set(frame, i * this.frameSize));
      const uid = this.transfer.dataset.addExample({ label: word, spectrogram: { data, frameSize: this.frameSize } });
      this.transfer.collateTransferWords();
      const example = { uid, frames };
      this.examples[word].push(example);
      // New data invalidates the trained head.
      this.trained = false;
      return example;
    }

    removeExample(word, uid) {
      this.transfer.removeExample(uid);
      this.examples[word] = this.examples[word].filter((example) => example.uid !== uid);
      this.trained = false;
    }

    clearWord(word) {
      this.examples[word].slice().forEach((example) => this.removeExample(word, example.uid));
    }

    /* Seconds since pressStart(), for the live "recording" display. */
    heldSeconds() {
      if (!this.capture || !this.capture.frames) return 0;
      return Math.max(0, this.capture.frames.length * this.capture.frameSeconds - PRE_ROLL_SECONDS);
    }

    /* Trains the new head; returns the final training accuracy (0..1).
     *
     * Same result as the library's transfer.train() - the head is one dense
     * layer on the base model's second-last dense layer, which is frozen -
     * but much faster: the library runs every example through the whole
     * convolutional base again at every epoch, freezing the page for seconds
     * on the first epochs. Here the base runs ONCE (its output never changes)
     * and the epochs train only the head on those embeddings. The head's
     * layer is shared with transfer.model, so listen() uses the new weights. */
    async train(onEpoch) {
      const transfer = this.transfer;
      if (!transfer.model) transfer.createTransferModelFromBaseModel();
      // Long examples cut into overlapping 1 s windows (the library's
      // default hop); mixing room noise into copies of the examples helps
      // with only a few of them.
      const { xs, ys } = transfer.collectTransferDataAsTensors(WINDOW_HOP_RATIO, {
        augmentByMixingNoiseRatio: this.settings.augmentNoiseRatio,
      });
      const embeddings = await this.embed(xs);
      xs.dispose();
      let lastAcc = 0;
      try {
        transfer.transferHead.compile({ loss: "categoricalCrossentropy", optimizer: "sgd", metrics: ["acc"] });
        await transfer.transferHead.fit(embeddings, ys, {
          epochs: this.settings.trainingEpochs,
          batchSize: BATCH_SIZE,
          shuffle: true,
          callbacks: {
            onEpochEnd: async (epoch, logs) => {
              lastAcc = logs.acc;
              onEpoch(epoch + 1, logs);
            },
          },
        });
      } finally {
        embeddings.dispose();
        ys.dispose();
      }
      this.trained = true;
      return lastAcc;
    }

    /* Base model output (second-last dense layer) for every window, computed
     * a few windows at a time with a pause in between, so the page (and the
     * training animation) never freezes for long. */
    async embed(xs) {
      const transfer = this.transfer;
      const embedder = tf.model({ inputs: transfer.baseModel.inputs, outputs: transfer.secondLastBaseDenseLayer.output });
      const parts = [];
      for (let start = 0; start < xs.shape[0]; start += EMBED_CHUNK) {
        const size = Math.min(EMBED_CHUNK, xs.shape[0] - start);
        const part = tf.tidy(() => embedder.predict(xs.slice(start, size)));
        await part.data();
        await tf.nextFrame(); // let the page draw between chunks
        parts.push(part);
      }
      const embeddings = tf.concat(parts);
      parts.forEach((part) => part.dispose());
      return embeddings;
    }

    /* Continuous recognition. onScores(labels, scores) on every analysis
     * window - thresholding is done by CommandDetector, so the UI can show
     * live probabilities for every class. */
    async listen(onScores) {
      // The library opens its own microphone for listening.
      this.closeMic();
      const labels = this.transfer.wordLabels();
      await this.transfer.listen(async (result) => onScores(labels, result.scores), {
        probabilityThreshold: 0,
        invokeCallbackOnNoiseAndUnknown: true,
        overlapFactor: this.settings.overlapFactor,
        suppressionTimeMillis: 0,
        audioTrackConstraints: AUDIO_CONSTRAINTS,
      });
    }

    async stopListening() {
      if (this.transfer && this.transfer.isListening()) {
        await this.transfer.stopListening();
      }
    }
  }

  /* Turns a stream of per-window probabilities into discrete commands:
   * fires when a command's probability >= threshold, then ignores everything
   * for suppressionMs (one sound spans several overlapping windows). */
  class CommandDetector {
    constructor(threshold, suppressionMs) {
      this.threshold = threshold;
      this.suppressionMs = suppressionMs;
      this.lastFired = 0;
    }

    /* Returns {command, score} or null. */
    feed(labels, scores) {
      let best = 0;
      for (let i = 1; i < scores.length; i++) if (scores[i] > scores[best]) best = i;
      const label = labels[best];
      if (!COMMANDS.includes(label) || scores[best] < this.threshold) return null;
      const now = performance.now();
      if (now - this.lastFired < this.suppressionMs) return null;
      this.lastFired = now;
      return { command: label, score: scores[best] };
    }
  }

  window.RunnerTrainer = { SoundTrainer, CommandDetector, BACKGROUND, COMMANDS };
})();
