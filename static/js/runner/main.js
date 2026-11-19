/* Game 4 page wiring: training UI -> SoundTrainer, runs -> RunnerGame,
 * finished scored runs -> POST /games/runner/api/run.
 *
 * Steps: 1 train (record examples, train), 2 play (run "trainer", run
 * "other", keyboard practice), 3 compare the two scored runs.
 * Everything about a team's model lives in this page only; switching team
 * starts over.
 */

(function () {
  "use strict";

  const { SoundTrainer, CommandDetector, BACKGROUND } = window.RunnerTrainer;
  const ICONS = { left: "fa-arrow-left", right: "fa-arrow-right", jump: "fa-arrow-up" };
  const TRAIN_ANIM_MIN_MS = 3000; // the training animation stays up at least this long

  document.addEventListener("DOMContentLoaded", () => {
    const cfg = GameKit.config();
    const settings = cfg.settings;
    const s = cfg.strings;
    const kit = GameKit.initGamePage();
    const trainer = new SoundTrainer(settings, cfg.urls);

    const decimalComma = (document.documentElement.lang || "it") === "it";
    const fmt = (text, vars) => text.replace(/\{(\w+)\}/g, (_, key) => vars[key]);
    const $ = (selector) => document.querySelector(selector);

    const statusEl = $("#runner-status");
    const trainBtn = $("#train-btn");
    const trainStatus = $("#train-status");
    const trainProgress = $("#train-progress");
    const trainAnim = $("#train-anim");
    const trainAnimStatus = $("#train-anim-status");
    const testBtn = $("#test-btn");
    const testBars = $("#test-bars");
    const playBars = $("#play-bars");
    const overlay = $("#runner-overlay");
    const runButtons = Array.from(document.querySelectorAll("[data-run]"));
    const cards = Array.from(document.querySelectorAll(".runner-cmd"));

    let results = {};          // phase -> last run result for the current team
    let testing = false;
    let activeRun = null;      // {phase, game}
    let currentTeamId = kit.picker.current().id;

    /* ------------------------------------------------------------- status */

    function showStatus(message, isError = false) {
      statusEl.textContent = message;
      statusEl.classList.toggle("runner-status--error", isError);
      statusEl.classList.toggle("hidden", !message);
    }

    /* -------------------------------------------------------------- steps */

    function showStep(step) {
      document.querySelectorAll("[data-step]").forEach((el) => el.classList.toggle("hidden", el.dataset.step !== step));
      document.querySelectorAll("[data-step-tab]").forEach((el) => el.classList.toggle("tab--active", el.dataset.stepTab === step));
      if (step === "compare") renderCompare();
    }
    document.querySelectorAll("[data-step-tab]").forEach((tab) => tab.addEventListener("click", () => {
      if (activeRun) return;
      showStep(tab.dataset.stepTab);
    }));

    /* ----------------------------------------------------------- training */

    function wordOf(card) {
      return card.dataset.command === "background" ? BACKGROUND : card.dataset.command;
    }

    /* keep: a button that stays enabled (the push-to-talk button being held -
     * disabling it would swallow its pointerup in some browsers). */
    function setBusy(busy, keep = null) {
      trainer.busy = busy;
      cards.forEach((card) => card.querySelectorAll("button").forEach((b) => { b.disabled = busy && b !== keep; }));
      // While only testing the commands, runs stay clickable (they stop the test).
      runButtons.forEach((b) => { b.disabled = busy && !testing; });
      refreshTrainControls();
    }

    function refreshTrainControls() {
      trainBtn.disabled = trainer.busy || !trainer.base || !trainer.isComplete();
      testBtn.disabled = (trainer.busy && !testing) || !trainer.trained;
    }

    /* Thumbnail of one example: its spectrogram (time left to right, low
     * pitches at the bottom), drawn in the accent colour. */
    const THUMB_HEIGHT = 40;
    function spectrogramThumb(frames) {
      const canvas = document.createElement("canvas");
      canvas.className = "runner-example__spec";
      canvas.width = frames.length;
      canvas.height = THUMB_HEIGHT;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
      let min = Infinity;
      let max = -Infinity;
      frames.forEach((f) => f.forEach((v) => { if (v < min) min = v; if (v > max) max = v; }));
      const range = Math.max(1, max - min);
      const binsPerRow = frames[0].length / THUMB_HEIGHT;
      frames.forEach((frame, x) => {
        for (let row = 0; row < THUMB_HEIGHT; row++) {
          let peak = -Infinity;
          const from = Math.floor(row * binsPerRow);
          const to = Math.floor((row + 1) * binsPerRow);
          for (let b = from; b < to; b++) if (frame[b] > peak) peak = frame[b];
          ctx.globalAlpha = Math.pow((peak - min) / range, 2);
          ctx.fillRect(x, THUMB_HEIGHT - 1 - row, 1, 1);
        }
      });
      return canvas;
    }

    /* The card's recordings as chips: number, spectrogram, x to delete. */
    function renderExamples(card) {
      const word = wordOf(card);
      const list = card.querySelector("[data-examples]");
      list.replaceChildren(...trainer.examples[word].map((example, index) => {
        const chip = document.createElement("div");
        chip.className = "runner-example";
        const num = document.createElement("span");
        num.className = "runner-example__num";
        num.textContent = word === BACKGROUND ? `${settings.backgroundSeconds} s` : `${index + 1}`;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "runner-example__remove";
        remove.title = s.remove_example;
        remove.setAttribute("aria-label", s.remove_example);
        remove.innerHTML = '<i class="fa-solid fa-xmark"></i>';
        remove.disabled = trainer.busy;
        remove.addEventListener("click", () => {
          trainer.removeExample(word, example.uid);
          renderCard(card);
          refreshTrainControls();
        });
        chip.append(num, spectrogramThumb(example.frames), remove);
        return chip;
      }));
    }

    function renderCard(card) {
      const word = wordOf(card);
      const count = trainer.count(word);
      const total = trainer.target(word);
      renderExamples(card);
      card.querySelector("[data-count]").textContent = word === BACKGROUND
        ? (count ? s.background_done : s.background_todo)
        : fmt(s.examples_count, { n: count, total });
      card.querySelector("[data-progress]").style.width = `${Math.min(100, (100 * count) / total)}%`;
      card.classList.toggle("runner-cmd--done", count >= total);
    }

    function renderAllCards() {
      cards.forEach(renderCard);
      refreshTrainControls();
    }

    /* Live label + level meter inside a card while it records. */
    function showLive(card, text) {
      const live = card.querySelector("[data-live]");
      const label = document.createElement("div");
      label.textContent = text;
      const meter = document.createElement("div");
      meter.className = "level-meter";
      const fill = document.createElement("div");
      fill.className = "level-meter__fill";
      meter.append(fill);
      live.replaceChildren(label, meter);
      live.classList.remove("hidden");
      card.classList.add("runner-cmd--active");
      return (level) => { fill.style.width = `${Math.round(level * 100)}%`; };
    }

    function hideLive(card) {
      card.querySelector("[data-live]").classList.add("hidden");
      card.classList.remove("runner-cmd--active");
    }

    function wordName(card) {
      const input = card.querySelector("[data-sound-name]");
      return input && input.value.trim() ? input.value.trim() : s[`cmd_${card.dataset.command}`];
    }

    /* Push-to-talk: hold the button (mouse, touch, or Space when focused),
     * say the word, release = one example. */
    function bindPushToTalk(card) {
      const btn = card.querySelector("[data-ptt]");
      const word = wordOf(card);
      let state = "idle";          // idle | opening | recording | saving
      let releasedEarly = false;

      async function press() {
        if (state !== "idle" || trainer.busy) return;
        state = "opening";
        releasedEarly = false;
        setBusy(true, btn);
        btn.classList.add("runner-ptt--held");
        const onLevel = showLive(card, fmt(s.say_word, { word: wordName(card) }));
        try {
          await trainer.openMic(onLevel);
        } catch (err) {
          showStatus(fmt(s.mic_failed, { error: err.message }), true);
          finish(false);
          return;
        }
        trainer.pressStart();
        state = "recording";
        btn.querySelector("span").textContent = s.release_to_save;
        const label = card.querySelector("[data-live] div");
        const tick = () => {
          if (state !== "recording") return;
          label.textContent = fmt(s.recording_word, {
            word: wordName(card), seconds: trainer.heldSeconds().toFixed(1).replace(".", decimalComma ? "," : "."),
          });
          requestAnimationFrame(tick);
        };
        tick();
        if (releasedEarly) release();
      }

      async function release() {
        if (state === "opening") {
          releasedEarly = true;
          return;
        }
        if (state !== "recording") return;
        state = "saving";
        btn.classList.remove("runner-ptt--held");
        card.querySelector("[data-live] div").textContent = s.saving_example;
        await trainer.pressEnd(word);
        finish(true);
      }

      function finish(saved) {
        state = "idle";
        btn.classList.remove("runner-ptt--held");
        btn.querySelector("span").textContent = s.hold_to_talk;
        hideLive(card);
        if (saved) renderCard(card);
        setBusy(false);
      }

      btn.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        // Release anywhere counts (the pointer may slide off the button).
        window.addEventListener("pointerup", release, { once: true });
        window.addEventListener("pointercancel", release, { once: true });
        press();
      });
      btn.addEventListener("keydown", (event) => {
        if (event.key !== " " && event.key !== "Enter") return;
        event.preventDefault();
        if (!event.repeat) press();
      });
      btn.addEventListener("keyup", (event) => {
        if (event.key !== " " && event.key !== "Enter") return;
        event.preventDefault();
        release();
      });
      // No click action: the press/release pair is the action.
      btn.addEventListener("click", (event) => event.preventDefault());
      btn.addEventListener("contextmenu", (event) => event.preventDefault());
    }

    async function recordBackground(card) {
      if (trainer.busy) return;
      setBusy(true);
      const onLevel = showLive(card, s.stay_silent);
      try {
        await trainer.openMic(onLevel);
        await trainer.recordBackground(settings.backgroundSeconds);
        renderCard(card);
      } catch (err) {
        showStatus(fmt(s.mic_failed, { error: err.message }), true);
      } finally {
        hideLive(card);
        setBusy(false);
      }
    }

    cards.forEach((card) => {
      if (card.dataset.command === "background") {
        card.querySelector("[data-record-bg]").addEventListener("click", () => recordBackground(card));
      } else {
        bindPushToTalk(card);
      }
      card.querySelector("[data-redo]").addEventListener("click", () => {
        trainer.clearWord(wordOf(card));
        renderCard(card);
        refreshTrainControls();
      });
    });

    trainBtn.addEventListener("click", async () => {
      if (!trainer.isComplete()) {
        showStatus(s.need_examples, true);
        return;
      }
      showStatus("");
      setBusy(true);
      trainStatus.textContent = s.training;
      trainAnimStatus.textContent = s.training;
      trainAnim.classList.remove("hidden");
      const shownAt = performance.now();
      try {
        // Let the browser draw the animation before the work starts.
        await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const acc = await trainer.train((epoch, logs) => {
          trainProgress.style.width = `${(100 * epoch) / settings.trainingEpochs}%`;
          trainStatus.textContent = fmt(s.epoch_progress, {
            epoch, total: settings.trainingEpochs, acc: Math.round(100 * logs.acc),
          });
          trainAnimStatus.textContent = trainStatus.textContent;
        });
        trainStatus.textContent = fmt(s.trained, { acc: Math.round(100 * acc) });
        // Training is often faster than a blink: keep the animation up long
        // enough for the class to see it.
        const left = TRAIN_ANIM_MIN_MS - (performance.now() - shownAt);
        if (left > 0) await new Promise((resolve) => setTimeout(resolve, left));
      } finally {
        trainAnim.classList.add("hidden");
        setBusy(false);
      }
    });

    /* --------------------------------------------------- probability bars */

    function labelText(label) {
      return label === BACKGROUND ? s.noise_label : s[`cmd_${label}`];
    }

    function renderBars(container, labels, scores, firedLabel) {
      if (container.children.length !== labels.length) {
        container.replaceChildren(...labels.map((label) => {
          const row = document.createElement("div");
          row.className = "runner-bar";
          row.dataset.label = label;
          row.innerHTML = '<i></i><div class="runner-bar__track"><div class="runner-bar__fill"></div></div><span class="runner-bar__value"></span>';
          row.querySelector("i").className = `fa-solid ${ICONS[label] || "fa-volume-xmark"}`;
          row.title = labelText(label);
          return row;
        }));
      }
      Array.from(container.children).forEach((row, i) => {
        const pct = Math.round(scores[i] * 100);
        row.querySelector(".runner-bar__fill").style.width = `${pct}%`;
        row.querySelector(".runner-bar__value").textContent = `${pct}%`;
        row.classList.toggle("runner-bar--over", scores[i] >= settings.probabilityThreshold);
        row.classList.toggle("runner-bar--fired", row.dataset.label === firedLabel);
      });
    }

    function showLastCommand(fired) {
      const el = $("#last-command");
      const icon = document.createElement("i");
      icon.className = `fa-solid ${ICONS[fired.command]}`;
      el.replaceChildren(icon, document.createTextNode(s[`cmd_${fired.command}`]));
      $("#last-confidence").textContent = `${Math.round(fired.score * 100)}%`;
    }

    async function startListening(container, onCommand) {
      const detector = new CommandDetector(settings.probabilityThreshold, settings.suppressionMs);
      await trainer.listen((labels, scores) => {
        const fired = detector.feed(labels, scores);
        renderBars(container, labels, scores, fired ? fired.command : null);
        if (fired) {
          showLastCommand(fired);
          onCommand(fired.command);
        }
      });
    }

    async function stopTest() {
      await trainer.stopListening();
      testing = false;
      testBars.classList.add("hidden");
      testBtn.querySelector("span").textContent = s.test_on;
      setBusy(false);
    }

    testBtn.addEventListener("click", async () => {
      if (testing) {
        await stopTest();
        return;
      }
      testing = true;
      setBusy(true);
      testBtn.querySelector("span").textContent = s.test_off;
      testBars.classList.remove("hidden");
      try {
        await startListening(testBars, () => {});
      } catch (err) {
        testing = false;
        setBusy(false);
        showStatus(fmt(s.mic_failed, { error: err.message }), true);
      }
    });

    /* --------------------------------------------------------------- runs */

    const hud = {
      time: $("#hud-time"), lives: $("#hud-lives"), coins: $("#hud-coins"), score: $("#hud-score"),
    };
    const game = new RunnerGame($("#runner-canvas"), settings, {
      onHud: (state) => {
        hud.time.textContent = state.timeLeft;
        hud.lives.textContent = state.lives;
        hud.coins.textContent = state.coins;
        hud.score.textContent = state.score;
      },
      onEnd: (result) => finishRun(result),
    });

    function showOverlay(main, sub = "") {
      overlay.replaceChildren(document.createTextNode(main));
      if (sub) {
        const small = document.createElement("small");
        small.textContent = sub;
        overlay.append(small);
      }
      overlay.classList.remove("hidden");
    }

    const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    async function countdown() {
      const hint = fmt(s.goal_hint, { points: settings.pointsPerCoin });
      for (const text of [s.get_ready, "3", "2", "1"]) {
        showOverlay(text, hint);
        await wait(text === s.get_ready ? 1500 : 800);
      }
      showOverlay(s.go);
      await wait(400);
      overlay.classList.add("hidden");
    }

    function onKey(event) {
      const map = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "jump", " ": "jump" };
      if (!map[event.key]) return;
      event.preventDefault();
      game.command(map[event.key]);
    }

    async function startRun(phase) {
      if (testing) await stopTest();
      if (activeRun || trainer.busy) return;
      if (phase !== "practice" && !trainer.trained) {
        showStatus(s.train_first, true);
        showStep("train");
        return;
      }
      showStatus("");
      showStep("play");
      activeRun = { phase };
      runButtons.forEach((b) => { b.disabled = true; });
      try {
        if (phase === "practice") {
          window.addEventListener("keydown", onKey);
        } else {
          await startListening(playBars, (command) => game.command(command));
        }
      } catch (err) {
        activeRun = null;
        runButtons.forEach((b) => { b.disabled = false; });
        showStatus(fmt(s.mic_failed, { error: err.message }), true);
        return;
      }
      // Bring the whole track on screen before the countdown (projector-friendly).
      $(".runner-stage").scrollIntoView({ block: "end" });
      await countdown();
      game.start();
    }

    async function finishRun(result) {
      const phase = activeRun.phase;
      window.removeEventListener("keydown", onKey);
      await trainer.stopListening();
      const reasonText = result.reason === "lives" ? s.run_over_lives : s.run_over_time;
      if (phase === "practice") {
        showOverlay(reasonText, s.practice_over);
      } else {
        showOverlay(reasonText, s.saving);
        await saveRun(phase, result, reasonText);
      }
      activeRun = null;
      runButtons.forEach((b) => { b.disabled = false; });
    }

    function soundNames() {
      const names = {};
      cards.forEach((card) => {
        const input = card.querySelector("[data-sound-name]");
        if (input && input.value.trim()) names[card.dataset.command] = input.value.trim();
      });
      return names;
    }

    async function saveRun(phase, result, reasonText) {
      const team = kit.picker.current();
      try {
        const saved = await GameKit.api(cfg.urls.run, {
          json: {
            team_id: team.id, phase, coins: result.coins, seconds: result.seconds, hits: result.hits,
            score: result.score, sounds: soundNames(),
          },
        });
        results[phase] = { ...result, points: saved.points };
        const message = saved.kept_previous
          ? fmt(s.kept_previous, { points: saved.points, best: saved.best })
          : fmt(s.saved_points, { points: saved.points });
        showOverlay(reasonText, message);
        window.showToast(message);
        kit.board.refresh();
      } catch (err) {
        showOverlay(reasonText, fmt(s.save_failed, { error: err.message }));
        showStatus(fmt(s.save_failed, { error: err.message }), true);
      }
    }

    runButtons.forEach((btn) => btn.addEventListener("click", () => startRun(btn.dataset.run)));

    /* ------------------------------------------------------------ compare */

    function renderCompare() {
      const rows = ["trainer", "other"].map((phase) => {
        const r = results[phase];
        const tr = document.createElement("tr");
        const cells = [s[`phase_${phase}`], r ? r.coins : "—", r ? r.seconds : "—", r ? r.hits : "—", r ? r.points : "—"];
        cells.forEach((value, i) => {
          const td = document.createElement(i === 0 ? "th" : "td");
          td.textContent = value;
          if (i > 0) td.className = "num";
          tr.append(td);
        });
        return tr;
      });
      $("#compare-rows").replaceChildren(...rows);
      const a = results.trainer;
      const b = results.other;
      let verdict = s.compare_missing;
      if (a && b) verdict = b.points > a.points ? s.compare_better : b.points < a.points ? s.compare_worse : s.compare_same;
      $("#compare-verdict").textContent = verdict;
    }

    /* -------------------------------------------------------- team change */

    async function resetForTeam() {
      if (activeRun) {
        game.stop();
        window.removeEventListener("keydown", onKey);
        activeRun = null;
      }
      testing = false;
      testBars.classList.add("hidden");
      testBtn.querySelector("span").textContent = s.test_on;
      trainer.closeMic();
      await trainer.reset();
      results = {};
      cards.forEach((card) => {
        const input = card.querySelector("[data-sound-name]");
        if (input) input.value = "";
      });
      overlay.classList.add("hidden");
      trainStatus.textContent = "";
      trainProgress.style.width = "0";
      $("#last-command").textContent = s.nothing_yet;
      $("#last-confidence").textContent = "";
      playBars.replaceChildren();
      setBusy(false);
      renderAllCards();
      showStep("train");
    }

    kit.picker.onChange(async (team) => {
      const hasWork = trainer.trained || trainer.hasAnyExample();
      if (hasWork && !window.confirm(s.confirm_team_change)) {
        kit.picker.select(currentTeamId, true);
        return;
      }
      currentTeamId = team.id;
      await resetForTeam();
    });

    /* ------------------------------------------------------------- start */

    async function init() {
      showStatus(s.loading_model);
      setBusy(true);
      try {
        await trainer.loadBase();
      } catch (err) {
        showStatus(fmt(s.model_load_failed, { error: err.message }), true);
        return;
      }
      showStatus("");
      setBusy(false);
      renderAllCards();
    }

    renderAllCards();
    init();
  });
})();
