/* Game 2 - "Voice Match"
 *
 * Two panels driven by one server state (GET api/state):
 *  - setup: volunteers per team, reference recording (WavRecorder, full
 *    quality), clip generation progress;
 *  - play: round tracker, the current clip, one guess per team, reveal.
 * The state is polled while clips are still being generated. Sections are
 * re-rendered only when their part of the state changed, so polling never
 * interrupts an <audio> element that is playing.
 */
(function () {
  "use strict";

  const cfg = GameKit.config();
  const S = cfg.strings;
  const kit = GameKit.initGamePage();
  const teamsById = Object.fromEntries(cfg.teams.map((team) => [team.id, team]));

  let state = null;
  let currentClipId = null;
  let pollTimer = null;
  let recorder = null;
  let recording = null; // { volunteerId, stop() } while a reference is being recorded
  const signatures = {};
  const roundKey = `voices-round:${cfg.teams.map((t) => t.id).join("-")}`;

  function withId(url, id) {
    return url.replace(/\/0(\/|$)/, `/${id}$1`);
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function icon(name) {
    return el("i", `fa-solid ${name}`);
  }

  function teamDot(team) {
    const dot = el("span", "team-dot");
    dot.style.background = team.color;
    return dot;
  }

  function fail(err) {
    window.showToast(err.message, "error");
  }

  /* --------------------------------------------------------------- state */

  async function load() {
    try {
      setState(await GameKit.api(cfg.urls.state));
    } catch (err) {
      fail(err);
    }
  }

  function setState(next) {
    state = next;
    renderSetup();
    renderPlay();
    schedulePoll();
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    if (state.jobRunning || state.counts.pending > 0) {
      pollTimer = setTimeout(load, 3000);
    }
  }

  function changed(section, data) {
    const signature = JSON.stringify(data);
    if (signatures[section] === signature) return false;
    signatures[section] = signature;
    return true;
  }

  /* --------------------------------------------------------------- tabs */

  document.querySelectorAll("[data-tab]").forEach((tab) => {
    tab.addEventListener("click", () => showTab(tab.dataset.tab));
  });

  function showTab(name) {
    document.querySelectorAll("[data-tab]").forEach((tab) => {
      tab.classList.toggle("tab--active", tab.dataset.tab === name);
      tab.setAttribute("aria-selected", tab.dataset.tab === name ? "true" : "false");
    });
    document.querySelectorAll("[data-panel]").forEach((panel) => {
      panel.classList.toggle("hidden", panel.dataset.panel !== name);
    });
  }

  /* --------------------------------------------------------------- setup */

  const teamCards = document.getElementById("team-cards");
  const level = document.getElementById("level");
  const generateBtn = document.getElementById("generate");
  const retryBtn = document.getElementById("retry");
  const progress = document.getElementById("progress");

  function renderSetup() {
    const c = state.counts;
    progress.textContent = c.total
      ? `${S.js_rounds_progress}: ${c.ready}/${c.total}` + (c.failed ? ` · ${S.js_failed}: ${c.failed}` : "")
        + (state.jobRunning ? ` · ${S.js_generating}` : "")
      : "";
    retryBtn.classList.toggle("hidden", c.failed === 0);
    const canGenerate = state.volunteers.some((v) => v.hasReference && !v.hasClips);
    generateBtn.disabled = !canGenerate;

    // Never rebuild the cards in the middle of a recording (the button is in them).
    if (recording || !changed("setup", state.volunteers)) return;
    teamCards.replaceChildren(...cfg.teams.map(renderTeamCard));
  }

  function renderTeamCard(team) {
    const card = el("div", "vo-team");
    card.style.setProperty("--team-color", team.color);
    const head = el("h3");
    head.append(teamDot(team), document.createTextNode(team.name));
    card.append(head);

    state.volunteers.filter((v) => v.teamId === team.id).forEach((volunteer) => {
      card.append(renderVolunteer(volunteer));
    });

    const form = el("form", "input-inline vo-add");
    const input = el("input");
    input.type = "text";
    input.maxLength = 60;
    input.placeholder = S.nickname_placeholder;
    input.setAttribute("aria-label", `${S.nickname_placeholder} - ${team.name}`);
    const add = el("button", "btn btn--ghost btn--sm");
    add.type = "submit";
    add.append(icon("fa-user-plus"));
    form.append(input, add);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const nickname = input.value.trim();
      if (!nickname) {
        window.showToast(S.js_nickname_required, "error");
        return;
      }
      try {
        setState(await GameKit.api(cfg.urls.addVolunteer, { json: { teamId: team.id, nickname } }));
      } catch (err) {
        fail(err);
      }
    });
    card.append(form);
    return card;
  }

  function renderVolunteer(volunteer) {
    const row = el("div", "vo-volunteer");
    row.append(el("span", "vo-volunteer__name", volunteer.nickname));
    row.append(el("span", `badge ${volunteer.hasReference ? "badge--success" : "badge--warning"}`,
      volunteer.hasReference ? S.js_has_reference : S.js_no_reference));

    if (volunteer.referenceUrl) {
      const audio = el("audio");
      audio.controls = true;
      audio.preload = "none";
      audio.src = `${volunteer.referenceUrl}?v=${Date.now()}`;
      audio.setAttribute("aria-label", `${S.js_reference_of} ${volunteer.nickname}`);
      row.append(audio);
    }

    if (volunteer.consent) {
      row.append(el("span", "badge badge--accent", S.js_consent_badge));
    }

    const needsConsent = cfg.requireConsent && !volunteer.consent;
    if (needsConsent && !volunteer.hasClips) {
      const label = el("label", "checkbox vo-consent");
      const box = el("input");
      box.type = "checkbox";
      box.addEventListener("change", async () => {
        if (!box.checked) return;
        box.disabled = true;
        try {
          signatures.setup = null;
          setState(await GameKit.api(withId(cfg.urls.consent, volunteer.id), { method: "POST" }));
        } catch (err) {
          box.checked = false;
          box.disabled = false;
          fail(err);
        }
      });
      label.append(box, el("span", "small", S.consent_label));
      row.append(label);
    }

    if (!volunteer.hasClips) {
      const rec = el("button", "btn btn--sm");
      rec.disabled = needsConsent;
      if (needsConsent) rec.title = S.err_consent_required;
      rec.type = "button";
      rec.append(icon("fa-microphone"), document.createTextNode(volunteer.hasReference ? S.js_rerecord : S.js_record));
      rec.addEventListener("click", () => toggleRecording(volunteer, rec));
      row.append(rec);

      const del = el("button", "icon-btn");
      del.type = "button";
      del.title = S.js_delete;
      del.setAttribute("aria-label", S.js_delete);
      del.append(icon("fa-trash"));
      del.addEventListener("click", async () => {
        if (!window.confirm(S.js_confirm_delete_volunteer)) return;
        try {
          setState(await GameKit.api(withId(cfg.urls.volunteer, volunteer.id), { method: "DELETE" }));
        } catch (err) {
          fail(err);
        }
      });
      row.append(del);
    }
    return row;
  }

  async function toggleRecording(volunteer, button) {
    if (recording) {
      if (recording.volunteerId === volunteer.id) recording.stop();
      return;
    }
    try {
      if (!recorder) recorder = new WavRecorder({ onLevel: (rms) => { level.style.width = `${Math.min(100, rms * 400)}%`; } });
      await recorder.open();
    } catch (err) {
      window.showToast(`${S.js_mic_error}: ${err.message}`, "error");
      return;
    }

    const started = Date.now();
    let finished = false;
    recorder.start();
    button.classList.add("btn--danger");

    const finish = async () => {
      if (finished) return;
      finished = true;
      clearInterval(ticker);
      const blob = await recorder.stop();
      recording = null;
      level.style.width = "0";
      const seconds = (Date.now() - started) / 1000;
      if (seconds < cfg.minReferenceSeconds) {
        window.showToast(S.js_too_short.replace("{n}", cfg.minReferenceSeconds), "error");
        signatures.setup = null;
        renderSetup();
        return;
      }
      const form = new FormData();
      form.append("audio", blob, "reference.wav");
      try {
        signatures.setup = null;
        setState(await GameKit.api(withId(cfg.urls.reference, volunteer.id), { formData: form }));
        window.showToast(S.js_saved);
      } catch (err) {
        fail(err);
        signatures.setup = null;
        renderSetup();
      }
    };

    const ticker = setInterval(() => {
      const left = Math.max(0, cfg.referenceSeconds - (Date.now() - started) / 1000);
      button.replaceChildren(icon("fa-stop"), document.createTextNode(`${S.js_stop} · ${Math.ceil(left)}s`));
      if (left <= 0) finish();
    }, 100);
    recording = { volunteerId: volunteer.id, stop: finish };
  }

  generateBtn.addEventListener("click", async () => {
    generateBtn.disabled = true;
    try {
      setState(await GameKit.api(cfg.urls.generate, { method: "POST" }));
    } catch (err) {
      fail(err);
      generateBtn.disabled = false;
    }
  });

  retryBtn.addEventListener("click", async () => {
    try {
      setState(await GameKit.api(cfg.urls.retry, { method: "POST" }));
    } catch (err) {
      fail(err);
    }
  });

  document.getElementById("delete-recordings").addEventListener("click", async () => {
    if (!window.confirm(S.js_confirm_delete_recordings)) return;
    try {
      signatures.setup = null;
      signatures.play = null;
      setState(await GameKit.api(cfg.urls.deleteRecordings, { method: "DELETE" }));
    } catch (err) {
      fail(err);
    }
  });

  /* ---------------------------------------------------------------- play */

  const tracker = document.getElementById("tracker");
  const stage = document.getElementById("stage");
  const guesses = document.getElementById("guesses");
  const revealBtn = document.getElementById("reveal");
  const prevBtn = document.getElementById("prev");
  const nextBtn = document.getElementById("next");
  let player = null;

  function currentClip() {
    const clips = state.clips;
    if (!clips.length) return null;
    let clip = clips.find((c) => c.id === currentClipId);
    if (!clip) {
      let remembered = null;
      try { remembered = Number(sessionStorage.getItem(roundKey)); } catch (err) { remembered = null; }
      clip = clips.find((c) => c.id === remembered) || clips.find((c) => !c.revealed) || clips[clips.length - 1];
      currentClipId = clip.id;
    }
    return clip;
  }

  function goTo(clip) {
    currentClipId = clip.id;
    try { sessionStorage.setItem(roundKey, String(clip.id)); } catch (err) { /* not remembered */ }
    if (player) player.pause();
    signatures.play = null;
    renderPlay();
  }

  function renderPlay() {
    const clip = currentClip();
    if (!changed("play", { clip, n: state.clips.map((c) => [c.id, c.status, c.revealed]), v: state.volunteers })) return;

    renderTracker(clip);
    const index = clip ? state.clips.indexOf(clip) : -1;
    prevBtn.disabled = index <= 0;
    nextBtn.disabled = index < 0;
    revealBtn.disabled = !clip || clip.status !== "ready";
    revealBtn.replaceChildren(icon("fa-eye"), document.createTextNode(clip && clip.revealed ? S.js_reveal_again : S.js_reveal));
    revealBtn.classList.toggle("btn--highlight", !(clip && clip.revealed));
    revealBtn.classList.toggle("btn--ghost", Boolean(clip && clip.revealed));

    renderStage(clip);
    renderGuesses(clip);
  }

  function renderTracker(current) {
    tracker.replaceChildren(...state.clips.map((clip) => {
      const button = el("button", "vo-round" + (current && clip.id === current.id ? " vo-round--current" : ""));
      button.type = "button";
      button.dataset.status = clip.status;
      button.dataset.revealed = clip.revealed ? "true" : "false";
      button.textContent = clip.revealed ? `${clip.round} ✓` : String(clip.round);
      button.title = `${S.js_round} ${clip.round} - ${S["js_" + clip.status] || clip.status}`;
      button.addEventListener("click", () => goTo(clip));
      return button;
    }));
  }

  function volunteerById(id) {
    return state.volunteers.find((v) => v.id === id);
  }

  function renderStage(clip) {
    if (!clip) {
      stage.replaceChildren(el("p", "stage__hint", S.js_no_clips));
      return;
    }
    const nodes = [el("div", "caption", `${S.js_round} ${clip.round} / ${state.clips.length}`)];
    if (clip.status === "pending") {
      nodes.push(el("div", "stage__big", "…"), el("p", "stage__hint", S.js_waiting_clip));
    } else if (clip.status === "failed") {
      nodes.push(el("div", "badge badge--danger", S.js_failed), el("p", "stage__hint", clip.error || ""));
    } else {
      const play = el("button", "vo-play");
      play.type = "button";
      play.setAttribute("aria-label", S.js_play_clip);
      play.title = S.js_play_clip;
      play.append(icon("fa-play"));
      play.addEventListener("click", () => playUrl(clip.audioUrl, play));
      nodes.push(play, el("div", "small muted", S.js_play_clip));

      if (clip.revealed) {
        const volunteer = volunteerById(clip.volunteerId);
        const team = teamsById[volunteer.teamId];
        const answer = el("div", "vo-answer");
        answer.append(el("span", "small muted", S.js_it_was), teamDot(team), document.createTextNode(`${volunteer.nickname}`),
          el("span", "small muted", `(${team.name})`));
        nodes.push(answer, el("p", "vo-phrase", `“${clip.phrase}”`));
        if (volunteer.referenceUrl) {
          const original = el("button", "btn btn--ghost");
          original.type = "button";
          original.append(icon("fa-user"), document.createTextNode(S.js_play_original));
          original.addEventListener("click", () => playUrl(volunteer.referenceUrl, original));
          nodes.push(original);
        }
      } else {
        nodes.push(el("div", "stage__big", S.js_choose));
      }
    }
    stage.replaceChildren(...nodes);
  }

  function playUrl(url, button) {
    if (player) player.pause();
    player = new Audio(url);
    button.disabled = true;
    const done = () => { button.disabled = false; };
    player.addEventListener("ended", done);
    player.addEventListener("pause", done);
    player.addEventListener("error", done);
    player.play().catch((err) => { done(); fail(err); });
  }

  function renderGuesses(clip) {
    if (!clip || clip.status !== "ready") {
      guesses.classList.add("hidden");
      return;
    }
    guesses.classList.remove("hidden");
    const answer = clip.revealed ? volunteerById(clip.volunteerId) : null;
    guesses.replaceChildren(...cfg.teams.map((team) => {
      const row = el("div", "vo-guess");
      const name = el("span", "team-name");
      name.append(teamDot(team), document.createTextNode(team.name));

      const select = el("select");
      select.setAttribute("aria-label", `${S.js_choose} - ${team.name}`);
      select.disabled = clip.revealed;
      select.append(new Option(`— ${S.js_choose} —`, ""));
      cfg.teams.forEach((group) => {
        const members = state.volunteers.filter((v) => v.teamId === group.id && v.hasClips);
        if (!members.length) return;
        const optgroup = el("optgroup");
        optgroup.label = group.name;
        members.forEach((v) => optgroup.append(new Option(`${v.nickname} (${group.name})`, String(v.id))));
        select.append(optgroup);
      });
      const guessed = clip.guesses[String(team.id)];
      select.value = guessed ? String(guessed) : "";
      select.addEventListener("change", () => sendGuess(clip, team, select.value));

      const result = el("span", "vo-guess__result");
      if (answer) {
        if (!guessed) {
          result.textContent = S.js_no_guess;
          result.classList.add("muted");
        } else if (guessed === answer.id) {
          const own = answer.teamId === team.id;
          const points = own && !cfg.ownTeamCanScore ? 0 : cfg.pointsCorrect;
          result.textContent = `${S.js_correct} +${GameKit.formatPoints(points)}` + (own && !cfg.ownTeamCanScore ? ` (${S.js_own_team})` : "");
          result.classList.add("vo-guess__result--right");
        } else {
          result.textContent = S.js_wrong;
          result.classList.add("vo-guess__result--wrong");
        }
      }
      row.append(name, select, result);
      return row;
    }));
  }

  async function sendGuess(clip, team, value) {
    try {
      const next = await GameKit.api(withId(cfg.urls.guess, clip.id), {
        json: { teamId: team.id, volunteerId: value ? Number(value) : null },
      });
      state = next;
      signatures.play = null;
      renderPlay();
    } catch (err) {
      fail(err);
    }
  }

  revealBtn.addEventListener("click", async () => {
    const clip = currentClip();
    if (!clip) return;
    try {
      signatures.play = null;
      setState(await GameKit.api(withId(cfg.urls.reveal, clip.id), { method: "POST" }));
      if (kit.board) kit.board.refresh();
    } catch (err) {
      fail(err);
    }
  });

  prevBtn.addEventListener("click", () => {
    const index = state.clips.indexOf(currentClip());
    if (index > 0) goTo(state.clips[index - 1]);
  });
  nextBtn.addEventListener("click", () => {
    const index = state.clips.indexOf(currentClip());
    if (index < state.clips.length - 1) goTo(state.clips[index + 1]);
    else window.showToast(S.js_all_done);
  });

  load().then(() => {
    if (state && state.clips.some((c) => c.status === "ready")) showTab("play");
  });
})();
