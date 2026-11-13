/* Drawing game (Visual Taboo AI).
 *
 * Flow: pick a scene -> the team types a description (forbidden words are
 * highlighted live; the server re-checks and is authoritative) -> "Draw it!"
 * -> image + detector boxes + the English text the model actually read ->
 * the instructor ticks/unticks elements -> "Confirm score".
 * The forbidden-word rules mirror services/forbidden_words.py.
 */
(function () {
  "use strict";

  const cfg = GameKit.config();
  const S = cfg.strings;
  const kit = GameKit.initGamePage();
  const $ = (id) => document.getElementById(id);

  const els = {
    sceneSelect: $("scene-select"), sceneRandom: $("scene-random"), title: $("scene-title"), brief: $("scene-brief"),
    elements: $("scene-elements"), forbidden: $("scene-forbidden"), prompt: $("prompt"), warning: $("forbidden-warning"),
    charsLeft: $("chars-left"), attemptsLeft: $("attempts-left"), language: $("prompt-language"), generate: $("generate"),
    tabs: $("attempt-tabs"), placeholder: $("image-placeholder"), placeholderText: $("placeholder-text"),
    canvas: $("result-canvas"), side: $("result-side"), translation: $("translation"), elapsed: $("elapsed"),
    showBoxes: $("show-boxes"), checks: $("element-checks"), scorePreview: $("score-preview"),
    confirm: $("confirm"), confirmLabel: $("confirm-label"),
  };
  const placeholderDefault = els.placeholderText.textContent;
  const sceneKey = `drawing-scene:${cfg.matchId}`;

  let challenge = null;
  let attempts = [];
  let selected = null;      // attempt shown
  let checked = new Set();  // element indices ticked for the shown attempt
  let image = null;         // loaded <img> of the shown attempt
  let busy = false;

  /* -------------------------------------------------- forbidden words */

  function normalize(text) {
    return text.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");
  }
  function tokenize(text) {
    return normalize(text).match(/[a-z]+/g) || [];
  }
  function stems(word) {
    const out = new Set([word]);
    if (word.length >= 4 && /[aeio]$/.test(word)) out.add(word.slice(0, -1));
    if (word.length >= 4 && word.endsWith("es")) out.add(word.slice(0, -2));
    if (word.length >= 4 && word.endsWith("s")) out.add(word.slice(0, -1));
    return out;
  }
  function findForbidden(text, forbidden) {
    const used = new Set();
    tokenize(text).forEach((tok) => stems(tok).forEach((s) => used.add(s)));
    return forbidden.filter((word) => tokenize(word).some((part) => [...stems(part)].some((s) => used.has(s))));
  }

  /* ------------------------------------------------------------ helpers */

  function boxColor(index) {
    const style = getComputedStyle(document.documentElement);
    const tokens = ["--highlight", "--accent", "--danger", "--success", "--warning"];
    return style.getPropertyValue(tokens[index % tokens.length]).trim();
  }

  function chip(text, className) {
    const span = document.createElement("span");
    span.className = `chip ${className}`;
    span.textContent = text;
    return span;
  }

  function attemptsLeft() {
    return Math.max(0, cfg.attemptsPerTeam - attempts.length);
  }

  /* -------------------------------------------------------------- scene */

  function populateScenes() {
    cfg.challenges.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.title;
      els.sceneSelect.append(opt);
    });
    let stored = null;
    try { stored = sessionStorage.getItem(sceneKey); } catch (err) { stored = null; }
    const initial = cfg.challenges.find((c) => String(c.id) === stored) || cfg.challenges[0];
    els.sceneSelect.value = initial.id;
    setScene(initial);
  }

  function setScene(c) {
    challenge = c;
    try { sessionStorage.setItem(sceneKey, String(c.id)); } catch (err) { /* not remembered */ }
    els.title.textContent = c.title;
    els.brief.textContent = c.brief;
    els.elements.replaceChildren(...c.elements.map((e) => chip(e.label, "chip--element")));
    els.prompt.value = "";
    checkPrompt();
    loadAttempts();
  }

  function randomScene() {
    const others = cfg.challenges.filter((c) => c.id !== challenge.id);
    const pool = others.length ? others : cfg.challenges;
    const pick = pool[Math.floor(Math.random() * pool.length)];
    els.sceneSelect.value = pick.id;
    setScene(pick);
  }

  /* ------------------------------------------------------------- prompt */

  function checkPrompt() {
    const text = els.prompt.value;
    const hits = findForbidden(text, challenge.forbidden);
    els.forbidden.replaceChildren(...challenge.forbidden.map((w) => chip(w, "chip--forbidden" + (hits.includes(w) ? " chip--hit" : ""))));
    els.warning.classList.toggle("hidden", hits.length === 0);
    els.warning.textContent = hits.length ? `${S.forbidden_live} ${hits.join(", ")}` : "";
    els.charsLeft.textContent = cfg.maxPromptChars - text.length;
    els.attemptsLeft.textContent = attemptsLeft();
    els.generate.disabled = busy || hits.length > 0 || !text.trim() || attemptsLeft() === 0 || !kit.model.isReady();
    return hits;
  }

  /* ----------------------------------------------------------- attempts */

  async function loadAttempts() {
    const team = kit.picker.current();
    const sceneId = challenge.id;
    const url = `${cfg.urls.attempts}?team_id=${team.id}&challenge_id=${sceneId}`;
    const data = await GameKit.api(url);
    if (challenge.id !== sceneId || kit.picker.current().id !== team.id) return; // changed meanwhile
    attempts = data.attempts;
    const confirmedAttempt = attempts.find((a) => a.is_confirmed);
    showAttempt(confirmedAttempt || attempts[attempts.length - 1] || null);
  }

  function renderTabs() {
    els.tabs.classList.toggle("hidden", attempts.length === 0);
    els.tabs.replaceChildren(...attempts.map((a, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tab" + (selected && selected.id === a.id ? " tab--active" : "");
      btn.textContent = `${S.attempt_n} ${i + 1}` + (a.is_confirmed ? " ✓" : "");
      btn.addEventListener("click", () => showAttempt(a));
      return btn;
    }));
  }

  function showAttempt(attempt) {
    selected = attempt;
    image = null;
    renderTabs();
    checkPrompt();
    if (!attempt) {
      els.canvas.classList.add("hidden");
      els.placeholder.classList.remove("hidden");
      els.placeholderText.textContent = placeholderDefault;
      els.side.classList.add("hidden");
      return;
    }
    els.side.classList.remove("hidden");
    // Empty when the image model read the description as typed (no translation step).
    els.translation.textContent = attempt.translated;
    document.getElementById("translation-block").classList.toggle("hidden", !attempt.translated);
    els.elapsed.textContent = "";
    checked = new Set(attempt.elements.map((e, i) => ((e.confirmed === null ? e.found : e.confirmed) ? i : -1)).filter((i) => i >= 0));
    renderChecks();
    if (attempt.image_url) {
      const img = new Image();
      img.onload = () => {
        if (selected !== attempt) return;
        image = img;
        els.placeholder.classList.add("hidden");
        els.canvas.classList.remove("hidden");
        draw();
      };
      img.src = attempt.image_url;
    }
  }

  function renderChecks() {
    els.checks.replaceChildren(...selected.elements.map((e, i) => {
      const label = document.createElement("label");
      label.className = "drawing-element" + (checked.has(i) ? " drawing-element--on" : "");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = checked.has(i);
      box.addEventListener("change", () => {
        if (box.checked) checked.add(i); else checked.delete(i);
        renderChecks();
        draw();
      });
      const swatch = document.createElement("span");
      swatch.className = "drawing-element__swatch";
      swatch.style.background = boxColor(i);
      const name = document.createElement("span");
      name.className = "drawing-element__name";
      name.textContent = e.label;
      const score = document.createElement("span");
      score.className = "drawing-element__score";
      score.textContent = `${e.found ? S.found : S.not_found} · ${Math.round(e.score * 100)}%`;
      label.append(box, swatch, name, score);
      return label;
    }));
    els.scorePreview.textContent = checked.size * cfg.pointsPerElement;
    els.confirmLabel.textContent = selected.is_confirmed ? S.confirmed : (attempts.some((a) => a.is_confirmed) ? S.reconfirm : S.confirm);
  }

  function draw() {
    if (!image) return;
    const ctx = els.canvas.getContext("2d");
    // Boxes are in the image's own pixels; the size depends on the image model.
    els.canvas.width = image.naturalWidth;
    els.canvas.height = image.naturalHeight;
    ctx.drawImage(image, 0, 0);
    if (!els.showBoxes.checked) return;
    // Same on-screen weight whatever the image size (tuned at 512 px).
    const k = image.naturalWidth / 512;
    ctx.lineWidth = 3 * k;
    ctx.font = `bold ${Math.round(16 * k)}px sans-serif`;
    selected.elements.forEach((e, i) => {
      if (!e.box || !(e.found || checked.has(i))) return;
      const [x0, y0, x1, y1] = e.box;
      const color = boxColor(i);
      ctx.strokeStyle = color;
      ctx.setLineDash(e.found ? [] : [6 * k, 4 * k]);
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      const text = `${e.label} ${Math.round(e.score * 100)}%`;
      const width = ctx.measureText(text).width + 8 * k;
      ctx.fillStyle = color;
      ctx.fillRect(x0, Math.max(0, y0 - 22 * k), width, 22 * k);
      ctx.fillStyle = "#0c3734";
      ctx.fillText(text, x0 + 4 * k, Math.max(16 * k, y0 - 6 * k));
    });
    ctx.setLineDash([]);
  }

  /* ----------------------------------------------------------- generate */

  async function generate() {
    const hits = checkPrompt();
    if (hits.length || busy) return;
    const team = kit.picker.current();
    busy = true;
    els.generate.disabled = true;
    els.canvas.classList.add("hidden");
    els.placeholder.classList.remove("hidden");
    const started = Date.now();
    const tick = setInterval(() => {
      els.placeholderText.textContent = `${S.generating} ${Math.round((Date.now() - started) / 1000)} s`;
    }, 500);
    els.placeholderText.textContent = S.generating;
    try {
      const data = await GameKit.api(cfg.urls.attempt, {
        json: { team_id: team.id, challenge_id: challenge.id, prompt: els.prompt.value, language: els.language.value },
      });
      attempts.push(data.attempt);
      showAttempt(data.attempt);
      els.elapsed.textContent = S.generated_in.replace("{s}", data.elapsed);
    } catch (err) {
      window.showToast(err.message, "error");
      els.placeholderText.textContent = err.message;
      if (selected) showAttempt(selected);
    } finally {
      clearInterval(tick);
      busy = false;
      checkPrompt();
    }
  }

  async function confirm() {
    if (!selected) return;
    const url = cfg.urls.confirm.replace("__ID__", selected.id);
    try {
      const data = await GameKit.api(url, { json: { elements: [...checked] } });
      attempts = attempts.map((a) => (a.id === data.attempt.id ? data.attempt : { ...a, is_confirmed: false, points: null }));
      selected = data.attempt;
      renderTabs();
      renderChecks();
      window.showToast(`+${data.points} ${S.points_awarded}`);
      kit.board.refresh();
    } catch (err) {
      window.showToast(err.message, "error");
    }
  }

  /* -------------------------------------------------------------- wire */

  els.sceneSelect.addEventListener("change", () => setScene(cfg.challenges.find((c) => String(c.id) === els.sceneSelect.value)));
  els.sceneRandom.addEventListener("click", randomScene);
  els.prompt.addEventListener("input", checkPrompt);
  els.generate.addEventListener("click", generate);
  els.confirm.addEventListener("click", confirm);
  els.showBoxes.addEventListener("change", draw);
  kit.picker.onChange(() => { els.prompt.value = ""; loadAttempts(); });
  kit.model.onChange(() => { if (challenge) checkPrompt(); });

  populateScenes();
})();
