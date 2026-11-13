/* GameKit: the small shared toolkit every game page uses.
 *
 *   GameKit.config()          - the page's JSON config (<script type="application/json" id="page-config">)
 *   GameKit.api(url, opts)    - fetch wrapper: CSRF header, JSON in/out, throws Error(message) on failure
 *   new GameKit.ModelStatus(el)  - starts the page's model process and shows a ready/starting badge
 *   new GameKit.TeamPicker(el)   - "whose turn is it" buttons, remembered per game
 *   new GameKit.TurnTimer(el)    - countdown for a team's turn, beeps at zero
 *   new GameKit.MiniBoard(el)    - live per-game leaderboard, refreshed after each score
 *
 * Markup for these lives in templates/partials/game_*.html; all user-facing
 * strings come from the server already translated (data-* attributes).
 */

(function () {
  "use strict";

  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]').content;
  }

  function config() {
    const node = document.getElementById("page-config");
    return node ? JSON.parse(node.textContent) : {};
  }

  async function api(url, opts = {}) {
    const init = { method: opts.method || (opts.json || opts.formData ? "POST" : "GET"), headers: {} };
    if (init.method !== "GET") init.headers["X-CSRFToken"] = csrfToken();
    if (opts.json) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.json);
    } else if (opts.formData) {
      init.body = opts.formData;
    }
    const response = await fetch(url, init);
    const isJson = (response.headers.get("Content-Type") || "").includes("application/json");
    const body = isJson ? await response.json() : null;
    if (!response.ok) {
      throw new Error((body && body.error) || `HTTP ${response.status}`);
    }
    return body;
  }

  /* ---------------------------------------------------------------- model */

  class ModelStatus {
    constructor(el) {
      this.el = el;
      this.statusUrl = el.dataset.statusUrl;
      this.startUrl = el.dataset.startUrl;
      this.labels = JSON.parse(el.dataset.labels);
      this.label = el.querySelector(".model-badge__label");
      this.retry = el.querySelector(".model-badge__retry");
      this.state = "stopped";
      this.listeners = [];
      this.timer = null;
      if (this.retry) this.retry.addEventListener("click", () => this.start());
      this.start();
    }

    onChange(callback) {
      this.listeners.push(callback);
      callback(this.state);
    }

    isReady() {
      return this.state === "ready";
    }

    async start() {
      this.render({ status: "starting" });
      try {
        this.render(await api(this.startUrl, { method: "POST" }));
      } catch (err) {
        this.render({ status: "failed", error: err.message });
      }
      this.schedule();
    }

    schedule() {
      clearTimeout(this.timer);
      const delay = this.state === "starting" ? 2000 : 10000;
      this.timer = setTimeout(() => this.poll(), delay);
    }

    async poll() {
      try {
        const status = await api(this.statusUrl);
        // A worker stopped by the idle reaper (or by another game starting
        // in exclusive mode) is restarted as soon as this page notices.
        if (status.status === "stopped") {
          await this.start();
          return;
        }
        this.render(status);
      } catch (err) {
        this.render({ status: "failed", error: err.message });
      }
      this.schedule();
    }

    render(status) {
      this.state = status.status;
      this.el.dataset.state = this.state;
      this.label.textContent = this.labels[this.state] || this.state;
      this.el.title = status.error || "";
      if (this.retry) this.retry.classList.toggle("hidden", this.state !== "failed");
      this.listeners.forEach((cb) => cb(this.state));
    }
  }

  /* ----------------------------------------------------------------- teams */

  class TeamPicker {
    constructor(el) {
      this.el = el;
      this.storageKey = `team-pick:${el.dataset.matchId}:${el.dataset.game}`;
      this.buttons = Array.from(el.querySelectorAll(".team-pick"));
      this.listeners = [];
      this.buttons.forEach((btn) => btn.addEventListener("click", () => this.select(btn.dataset.teamId)));
      let initial = null;
      try { initial = sessionStorage.getItem(this.storageKey); } catch (err) { initial = null; }
      const exists = this.buttons.some((b) => b.dataset.teamId === initial);
      this.select(exists ? initial : this.buttons[0].dataset.teamId, true);
    }

    onChange(callback) {
      this.listeners.push(callback);
    }

    select(teamId, silent = false) {
      this.currentId = String(teamId);
      this.buttons.forEach((btn) => {
        const active = btn.dataset.teamId === this.currentId;
        btn.classList.toggle("team-pick--active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
      });
      try { sessionStorage.setItem(this.storageKey, this.currentId); } catch (err) { /* private mode: just not remembered */ }
      if (!silent) this.listeners.forEach((cb) => cb(this.current()));
    }

    current() {
      const btn = this.buttons.find((b) => b.dataset.teamId === this.currentId);
      return { id: Number(btn.dataset.teamId), name: btn.dataset.teamName, color: btn.dataset.teamColor };
    }

    teams() {
      return this.buttons.map((b) => ({ id: Number(b.dataset.teamId), name: b.dataset.teamName, color: b.dataset.teamColor }));
    }

    setPoints(pointsByTeamId) {
      this.buttons.forEach((btn) => {
        const span = btn.querySelector(".team-pick__points");
        if (span) span.textContent = formatPoints(pointsByTeamId[btn.dataset.teamId] ?? 0);
      });
    }
  }

  /* ----------------------------------------------------------------- timer */

  function beep(durationMs = 600, frequency = 880) {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = frequency;
    gain.gain.value = 0.2;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    setTimeout(() => { osc.stop(); ctx.close(); }, durationMs);
  }

  class TurnTimer {
    constructor(el) {
      this.el = el;
      this.total = Number(el.dataset.seconds);
      this.valueEl = el.querySelector(".turn-timer__value");
      this.toggleBtn = el.querySelector("[data-timer-toggle]");
      this.resetBtn = el.querySelector("[data-timer-reset]");
      this.labels = JSON.parse(el.dataset.labels);
      this.toggleBtn.addEventListener("click", () => (this.running ? this.pause() : this.start()));
      this.resetBtn.addEventListener("click", () => this.reset());
      this.reset();
    }

    start() {
      if (this.remaining <= 0) this.remaining = this.total;
      this.running = true;
      this.lastTick = Date.now();
      this.interval = setInterval(() => this.tick(), 250);
      this.render();
    }

    pause() {
      this.running = false;
      clearInterval(this.interval);
      this.render();
    }

    reset() {
      this.pause();
      this.remaining = this.total;
      this.render();
    }

    tick() {
      const now = Date.now();
      this.remaining -= (now - this.lastTick) / 1000;
      this.lastTick = now;
      if (this.remaining <= 0) {
        this.remaining = 0;
        this.pause();
        beep();
      }
      this.render();
    }

    render() {
      const secs = Math.ceil(this.remaining);
      const m = Math.floor(secs / 60);
      const s = String(secs % 60).padStart(2, "0");
      this.valueEl.textContent = `${m}:${s}`;
      this.el.dataset.state = secs === 0 ? "over" : secs <= 20 ? "warning" : "normal";
      this.toggleBtn.innerHTML = this.running
        ? `<i class="fa-solid fa-pause"></i>${this.labels.pause}`
        : `<i class="fa-solid fa-play"></i>${this.labels.start}`;
    }
  }

  /* ------------------------------------------------------------ mini board */

  class MiniBoard {
    constructor(el, picker) {
      this.el = el;
      this.url = el.dataset.url;
      this.game = el.dataset.game;
      this.picker = picker;
      this.list = el.querySelector(".mini-board");
      this.refresh();
    }

    async refresh() {
      const data = await api(this.url);
      const rows = data.per_game[this.game];
      const points = {};
      this.list.replaceChildren(...rows.map((row) => {
        points[row.team.id] = row.points;
        const div = document.createElement("div");
        div.className = "mini-board__row";
        div.innerHTML = `<span class="mini-board__rank"></span><span class="team-dot"></span>
          <span class="mini-board__name"></span><span class="mini-board__pts"></span>`;
        div.querySelector(".mini-board__rank").textContent = row.rank;
        div.querySelector(".team-dot").style.background = row.team.color;
        div.querySelector(".mini-board__name").textContent = row.team.name;
        div.querySelector(".mini-board__pts").textContent = formatPoints(row.points);
        return div;
      }));
      if (this.picker) this.picker.setPoints(points);
    }
  }

  /* ------------------------------------------------------------- wiring */

  function initGamePage() {
    const out = {};
    const modelEl = document.querySelector("[data-model-badge]");
    if (modelEl) out.model = new ModelStatus(modelEl);
    const pickerEl = document.querySelector("[data-team-picker]");
    if (pickerEl) out.picker = new TeamPicker(pickerEl);
    const timerEl = document.querySelector("[data-turn-timer]");
    if (timerEl) out.timer = new TurnTimer(timerEl);
    const boardEl = document.querySelector("[data-mini-board]");
    if (boardEl) out.board = new MiniBoard(boardEl, out.picker);
    if (out.picker && out.timer) out.picker.onChange(() => out.timer.reset());
    return out;
  }

  /* Points in the page language: 5, 2,5 (it) / 2.5 (en). */
  function formatPoints(value) {
    return new Intl.NumberFormat(document.documentElement.lang || undefined, { maximumFractionDigits: 2 }).format(value);
  }

  window.GameKit = { config, api, beep, formatPoints, ModelStatus, TeamPicker, TurnTimer, MiniBoard, initGamePage };
})();
