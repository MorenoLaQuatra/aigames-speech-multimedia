/* AudioWorklet that forwards raw mono Float32 samples to the main thread
 * (used by static/js/recorder.js). Output is left silent. */

class PcmCapture extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input && input[0]) {
      this.port.postMessage(input[0].slice(0));
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
