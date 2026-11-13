/* Dark-mode toggle.
 *
 * The theme is stored on the account (User.theme) so it follows the user
 * between devices, and mirrored into localStorage so base.html's inline script
 * can apply it before first paint without waiting for the server round trip.
 */

document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.querySelector(".theme-toggle");
  if (!toggle) return;

  toggle.addEventListener("click", async () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("theme", next);

    const saveUrl = toggle.dataset.saveUrl;
    if (!saveUrl) return;
    const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
    try {
      await fetch(saveUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": csrfToken,
        },
        body: `theme=${next}&csrf_token=${encodeURIComponent(csrfToken)}`,
      });
    } catch (err) {
      // The visible theme already changed and localStorage keeps it across
      // reloads; only the cross-device sync is lost, which is not worth
      // interrupting the user for.
    }
  });
});
