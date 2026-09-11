
document.addEventListener("DOMContentLoaded", () => {
  const modal = document.getElementById("admin-report-review-modal");
  if (!modal) return;

  const title = modal.querySelector("#arr-modal-title");
  const message = modal.querySelector("[data-review-message]");
  const statusInput = modal.querySelector("[data-review-status]");
  const submit = modal.querySelector("[data-review-submit]");
  const warning = modal.querySelector("[data-review-warning]");

  const open = (button) => {
    const status = button.dataset.status || "";
    title.textContent = button.dataset.title || "Kararı onayla";
    message.textContent = button.dataset.message || "";
    statusInput.value = status;
    submit.textContent = button.dataset.submitLabel || "Kararı Onayla";

    const isDanger = status === "ABUSIVE";
    submit.classList.toggle("is-danger", isDanger);
    warning.hidden = !isDanger;

    modal.hidden = false;
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("arr-modal-open");
    window.setTimeout(() => submit.focus(), 30);
  };

  const close = () => {
    modal.classList.remove("is-open");
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("arr-modal-open");
  };

  document.querySelectorAll("[data-review-open]").forEach((button) => {
    button.addEventListener("click", () => open(button));
  });

  modal.querySelectorAll("[data-review-close]").forEach((button) => {
    button.addEventListener("click", close);
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });

  const card = modal.querySelector(".arr-modal-card");
  if (card) {
    card.addEventListener("click", (event) => event.stopPropagation());
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.classList.contains("is-open")) {
      close();
    }
  });
});
