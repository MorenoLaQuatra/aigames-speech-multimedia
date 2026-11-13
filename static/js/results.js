/* Results page: print button. */
document.addEventListener("DOMContentLoaded", () => {
  const button = document.querySelector("[data-print]");
  if (button) button.addEventListener("click", () => window.print());
});
