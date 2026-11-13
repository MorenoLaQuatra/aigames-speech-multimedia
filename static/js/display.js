/* Projector view: live standings, refreshed every few seconds.
 *
 * "Reveal" mode for the final ceremony: "Hide" blanks the final ranking,
 * then each "Reveal" click shows one more team, from last place to first.
 * The per-game panels always stay visible.
 */
(function () {
  "use strict";

  const cfg = GameKit.config();
  const finalList = document.getElementById("final-list");
  const gameList = document.getElementById("game-list");
  // null = everything visible; a number = how many teams (from the bottom) are revealed.
  let revealed = null;
  let lastData = null;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderFinal(data) {
    const rows = data.final;
    finalList.replaceChildren(...rows.map((row, index) => {
      const fromBottom = rows.length - index;
      const hidden = revealed !== null && fromBottom > revealed;
      const div = el("div", "display-row" + (row.rank === 1 && data.played.length ? " display-row--first" : "") + (hidden ? " display-row--hidden" : ""));
      div.append(el("span", "display-row__rank", row.rank));
      const dot = el("span", "team-dot");
      dot.style.background = row.team.color;
      dot.style.width = dot.style.height = "20px";
      div.append(dot, el("span", "display-row__name", row.team.name),
        el("span", "display-row__pts", `${row.placement_total} ${cfg.strings.points}`));
      return div;
    }));
  }

  function renderGames(data) {
    gameList.replaceChildren(...cfg.games.map((game) => {
      const box = el("div", "display-game");
      const head = el("h3");
      head.append(el("i", `fa-solid ${game.icon}`), document.createTextNode(game.title));
      box.append(head);
      if (!data.played.includes(game.slug)) {
        box.append(el("div", "display-game__row", cfg.strings.notPlayed));
        return box;
      }
      data.per_game[game.slug].forEach((row) => {
        const line = el("div", "display-game__row");
        const dot = el("span", "team-dot");
        dot.style.background = row.team.color;
        line.append(el("strong", "", `${row.rank}°`), dot, el("span", "", row.team.name), el("strong", "", GameKit.formatPoints(row.points)));
        box.append(line);
      });
      return box;
    }));
  }

  async function refresh() {
    try {
      lastData = await GameKit.api(cfg.url);
      renderFinal(lastData);
      renderGames(lastData);
    } finally {
      setTimeout(refresh, cfg.refreshMs);
    }
  }

  const revealBtn = document.getElementById("reveal-next");
  const hideBtn = document.getElementById("hide-all");

  // "Reveal" only makes sense once the ranking has been hidden.
  function syncButtons() {
    const total = lastData ? lastData.final.length : 0;
    revealBtn.classList.toggle("hidden", revealed === null || revealed >= total);
    hideBtn.classList.toggle("hidden", revealed !== null && revealed < total);
  }

  revealBtn.addEventListener("click", () => {
    if (!lastData || revealed === null) return;
    revealed += 1;
    if (revealed >= lastData.final.length) revealed = null;
    renderFinal(lastData);
    syncButtons();
  });
  hideBtn.addEventListener("click", () => {
    revealed = 0;
    if (lastData) renderFinal(lastData);
    syncButtons();
  });
  syncButtons();
  document.getElementById("fullscreen").addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen();
  });

  refresh();
})();
