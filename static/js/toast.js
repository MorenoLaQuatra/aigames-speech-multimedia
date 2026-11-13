/* Transient confirmations ("Saved", "+3 points"), shared by every page. */

const TOAST_VISIBLE_MS = 1800;

const TOAST_ICONS = {
  success: "fa-circle-check",
  error: "fa-circle-exclamation",
  info: "fa-circle-info",
};

function toastStack() {
  let stack = document.getElementById("toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "toast-stack";
    stack.className = "toast-stack";
    stack.setAttribute("role", "status");
    stack.setAttribute("aria-live", "polite");
    document.body.appendChild(stack);
  }
  return stack;
}

window.showToast = function showToast(message, kind = "success") {
  const toast = document.createElement("div");
  toast.className = `toast toast--${kind}`;

  const icon = document.createElement("i");
  icon.className = `fa-solid ${TOAST_ICONS[kind] || TOAST_ICONS.info}`;
  toast.appendChild(icon);

  const text = document.createElement("span");
  text.textContent = message;
  toast.appendChild(text);

  const stack = toastStack();
  stack.appendChild(toast);
  window.setTimeout(() => toast.remove(), TOAST_VISIBLE_MS);
};
