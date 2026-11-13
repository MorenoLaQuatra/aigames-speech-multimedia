/* Full-screen results of one game (shown after "Concludi gioco").
 *
 * Every team starts hidden; each "Rivela" click shows one more, from last
 * place to first, with its points in the game and the placement points it
 * earns for the final ranking (10/8/6/4). "Mostra tutti" shows everything.
 * The game is finished (its points are locked), so the standings are loaded
 * once - no polling.
 */
(function () {
  "use strict";

  const cfg = GameKit.config();
  const list = document.getElementById("game-rows");
  const revealBtn = document.getElementById("reveal-next");
  const showAllBtn = document.getElementById("show-all");
  let rows = [];
  let revealed = 0; // how many teams, counted from the last, are visible

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function render() {
    list.replaceChildren(...rows.map((row, index) => {
      const fromBottom = rows.length - index;
      const hidden = fromBottom > revealed;
      const div = el("div", "display-row" + (row.rank === 1 ? " display-row--first" : "") +
        (hidden ? " display-row--hidden" : ""));
      div.append(el("span", "display-row__rank", `${row.rank}°`));
      const dot = el("span", "team-dot team-dot--lg");
      dot.style.background = row.team.color;
      div.append(dot, el("span", "display-row__name", row.team.name),
        el("span", "display-row__game-pts", GameKit.formatPoints(row.points)),
        el("span", "display-row__placement", `+${row.placement_points}`));
      return div;
    }));
    const done = revealed >= rows.length;
    revealBtn.classList.toggle("hidden", done);
    showAllBtn.classList.toggle("hidden", done);
  }

  function showNotPlayed() {
    list.replaceChildren(el("div", "display-row", cfg.strings.notPlayed));
    revealBtn.classList.add("hidden");
    showAllBtn.classList.add("hidden");
  }

  revealBtn.addEventListener("click", () => {
    revealed = Math.min(revealed + 1, rows.length);
    render();
  });
  showAllBtn.addEventListener("click", () => {
    revealed = rows.length;
    render();
  });
  document.getElementById("fullscreen").addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen();
  });

  GameKit.api(cfg.url).then((data) => {
    if (!data.played.includes(cfg.game)) {
      showNotPlayed();
      return;
    }
    rows = data.per_game[cfg.game];
    render();
  });
})();
