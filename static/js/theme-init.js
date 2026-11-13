/* Applies the theme before first paint (loaded synchronously in <head>).
 * Order: the account's saved theme, then localStorage, then the OS setting. */
(function () {
  var serverTheme = document.currentScript.dataset.serverTheme;
  var stored = null;
  try { stored = localStorage.getItem("theme"); } catch (err) { stored = null; }
  var theme = serverTheme || stored
    || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("theme", theme); } catch (err) { /* private mode */ }
})();
