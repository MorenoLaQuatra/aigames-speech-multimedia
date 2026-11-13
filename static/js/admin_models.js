/* Admin > Models: live status of the model processes, start/stop buttons. */
document.addEventListener("DOMContentLoaded", () => {
  const cfg = GameKit.config();
  const s = cfg.strings;
  const tbody = document.getElementById("worker-rows");

  function fmt(seconds) {
    if (!seconds) return "—";
    const m = Math.floor(seconds / 60);
    return m ? `${m} min` : `${seconds} s`;
  }

  function badge(status) {
    const kind = { ready: "success", starting: "warning", failed: "danger" }[status] || "";
    const span = document.createElement("span");
    span.className = `badge ${kind ? "badge--" + kind : ""}`;
    span.textContent = s[status] || status;
    return span;
  }

  async function act(url) {
    try {
      await GameKit.api(url, { method: "POST" });
    } catch (err) {
      window.showToast(err.message, "error");
    }
    refresh();
  }

  function render(workers) {
    tbody.replaceChildren(...workers.map((w) => {
      const tr = document.createElement("tr");
      const cells = [s.names[w.name] || w.name, null, w.device, fmt(w.uptime_seconds), w.status === "ready" ? fmt(w.idle_seconds) : "—"];
      cells.forEach((value, i) => {
        const td = document.createElement("td");
        if (i === 1) {
          td.append(badge(w.status));
          if (w.error) { const c = document.createElement("div"); c.className = "caption"; c.textContent = w.error; td.append(c); }
        } else {
          td.textContent = value;
        }
        tr.append(td);
      });
      const actions = document.createElement("td");
      actions.className = "text-right";
      const running = w.status === "ready" || w.status === "starting";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = running ? "btn btn--sm btn--danger-ghost" : "btn btn--sm";
      btn.textContent = running ? s.stop : s.start;
      btn.addEventListener("click", () => act((running ? cfg.stopUrl : cfg.startUrl).replace("__NAME__", w.name)));
      actions.append(btn);
      tr.append(actions);
      return tr;
    }));
  }

  async function refresh() {
    const data = await GameKit.api(cfg.statusUrl);
    render(data.workers);
  }

  document.getElementById("stop-all").addEventListener("click", (e) => act(e.currentTarget.dataset.url));
  refresh();
  setInterval(refresh, 3000);
});
