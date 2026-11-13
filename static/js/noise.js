/* Game 1 - "Imita il suono".
 *
 * Steps: idle -> target (draw a sound, countdown, record) -> result.
 * Recording uses WavRecorder (full-quality float WAV); the server forwards
 * it to the classifier, scores the attempt, and returns the predictions.
 */
document.addEventListener("DOMContentLoaded", () => {
  "use strict";

  const cfg = GameKit.config();
  const s = cfg.strings;
  const kit = GameKit.initGamePage();
  const GO_BEEP_MS = 200;
  const BEEP_DECAY_MS = 400;

  const steps = Array.from(document.querySelectorAll(".noise-step"));
  const recordBtn = document.getElementById("record-btn");
  const recordHint = document.getElementById("record-hint");
  const countdownEl = document.getElementById("countdown");
  const levelEl = document.getElementById("level");
  const playbackBtn = document.getElementById("playback-btn");

  let target = null;
  let busy = false;
  let lastUrl = null;
  let recorder = null;

  function showStep(name) {
    steps.forEach((el) => el.classList.toggle("hidden", el.dataset.step !== name));
  }

  function updateRecordButton() {
    recordBtn.disabled = busy || !kit.model.isReady();
    if (!busy) recordHint.textContent = kit.model.isReady() ? recordHint.dataset.ready : s.modelNotReady;
  }
  recordHint.dataset.ready = recordHint.textContent;
  kit.model.onChange(updateRecordButton);

  async function drawTarget() {
    const team = kit.picker.current();
    const params = new URLSearchParams({ team_id: team.id });
    if (target) params.set("current_id", target.id);
    try {
      target = await GameKit.api(`${cfg.nextUrl}?${params}`);
    } catch (err) {
      window.showToast(err.message, "error");
      return;
    }
    document.getElementById("target-emoji").textContent = target.emoji;
    document.getElementById("target-name").textContent = target.name;
    showStep("target");
    updateRecordButton();
  }

  async function ensureRecorder() {
    if (recorder) return recorder;
    recorder = new WavRecorder({
      onLevel: (rms) => { levelEl.style.width = `${Math.min(100, rms * 400)}%`; },
    });
    await recorder.open();
    return recorder;
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function countdown() {
    countdownEl.classList.remove("hidden");
    for (let n = cfg.countdownSeconds; n > 0; n--) {
      countdownEl.textContent = n;
      GameKit.beep(120, 660);
      await sleep(1000);
    }
    countdownEl.classList.add("hidden");
    // The "go" beep comes out of the speakers and the mic has no echo
    // cancellation (on purpose), so recording must start only after the beep
    // and its room echo have died out - otherwise the classifier hears
    // "Beep, bleep" every time.
    GameKit.beep(GO_BEEP_MS, 990);
    await sleep(GO_BEEP_MS + BEEP_DECAY_MS);
  }

  async function record() {
    if (busy || !target) return;
    busy = true;
    updateRecordButton();
    try {
      const rec = await ensureRecorder();
      recordHint.textContent = s.getReady;
      await countdown();
      recordBtn.dataset.recording = "true";
      const blob = await rec.recordFor(cfg.recordSeconds, (left) => {
        recordHint.textContent = `${s.recording} ${left.toFixed(1)}s`;
      });
      recordBtn.dataset.recording = "false";
      if (lastUrl) URL.revokeObjectURL(lastUrl);
      lastUrl = URL.createObjectURL(blob);
      recordHint.textContent = s.thinking;
      await submit(blob);
    } catch (err) {
      recordBtn.dataset.recording = "false";
      const message = err.name === "NotAllowedError" || err.name === "NotFoundError" ? s.micError : err.message;
      window.showToast(message, "error");
      recordHint.textContent = recordHint.dataset.ready;
    } finally {
      busy = false;
      updateRecordButton();
    }
  }

  async function submit(blob) {
    const form = new FormData();
    form.append("team_id", kit.picker.current().id);
    form.append("target_id", target.id);
    form.append("audio", blob, "imitation.wav");
    const result = await GameKit.api(cfg.attemptUrl, { formData: form });
    renderResult(result);
    kit.board.refresh();
  }

  function renderResult(result) {
    const banner = document.getElementById("result-banner");
    document.getElementById("result-emoji").textContent = target.emoji;
    if (result.rank && !result.alreadyScored) {
      banner.className = "result-banner result-banner--win";
      banner.textContent = `${s.hit} +${result.points}`;
      GameKit.beep(150, 1320);
    } else if (result.alreadyScored) {
      banner.className = "result-banner result-banner--miss";
      banner.textContent = s.alreadyScored;
    } else {
      banner.className = "result-banner result-banner--miss";
      banner.textContent = s.miss;
    }
    if (result.rms < 0.003) window.showToast(s.tooQuiet, "error");

    const targetLabels = new Set(result.targetLabels);
    const top = result.predictions.slice(0, cfg.topK);
    const maxScore = Math.max(...top.map((p) => p.score), 0.0001);
    document.getElementById("pred-list").replaceChildren(...top.map((p, i) => {
      const row = document.createElement("div");
      row.className = "pred" + (targetLabels.has(p.label) ? " pred--hit pred--target" : "");
      row.innerHTML = `<span class="pred__rank"></span>
        <div class="pred__bar"><div class="pred__fill"></div><div class="pred__label"></div></div>
        <span class="pred__value"></span>`;
      row.querySelector(".pred__rank").textContent = i + 1;
      row.querySelector(".pred__fill").style.width = `${(p.score / maxScore) * 100}%`;
      row.querySelector(".pred__label").textContent = p.label;
      row.querySelector(".pred__value").textContent = `${Math.round(p.score * 100)}%`;
      return row;
    }));
    showStep("result");
  }

  document.querySelectorAll('[data-action="next"]').forEach((btn) => btn.addEventListener("click", () => {
    if (!busy) drawTarget();
  }));
  document.querySelector('[data-action="retry"]').addEventListener("click", () => {
    showStep("target");
    updateRecordButton();
  });
  recordBtn.addEventListener("click", record);
  playbackBtn.addEventListener("click", () => {
    if (lastUrl) new Audio(lastUrl).play();
  });
  // A new team starts from a fresh draw.
  kit.picker.onChange(() => {
    if (busy) return;
    target = null;
    showStep("idle");
  });
});
