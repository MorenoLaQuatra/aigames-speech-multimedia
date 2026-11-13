/* Submit-time feedback for slow full-page form posts.
 * Opt in with class="js-loading-submit": disables the buttons and swaps the
 * clicked button's label to its data-loading-text. Also handles
 * class="js-confirm" forms: asks data-confirm before submitting. */

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("select.js-autosubmit").forEach((select) => {
    select.addEventListener("change", () => select.form.requestSubmit());
  });

  document.querySelectorAll("form.js-confirm").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  document.querySelectorAll("form.js-loading-submit").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.submitting === "true") {
        event.preventDefault();
        return;
      }
      form.dataset.submitting = "true";

      const clicked = event.submitter;
      form.querySelectorAll("button").forEach((btn) => { btn.disabled = true; });

      const target = clicked || form.querySelector('button[type="submit"]');
      if (target) {
        target.textContent = target.dataset.loadingText || "Working...";
      }
      document.body.style.cursor = "progress";
    });
  });
});
