
document.addEventListener("DOMContentLoaded", () => {
  const openModal = (modal) => {
    if (!modal) return;
    modal.classList.add("is-open");
    modal.removeAttribute("hidden");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("report-modal-open");

    const firstField = modal.querySelector(
      "select, textarea, input:not([type='hidden']), button"
    );
    if (firstField) {
      window.setTimeout(() => firstField.focus(), 20);
    }
  };

  const closeModal = (modal) => {
    if (!modal) return;
    modal.classList.remove("is-open");
    modal.setAttribute("hidden", "");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("report-modal-open");
  };

  document.querySelectorAll("[data-report-open]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const modalId = button.getAttribute("data-report-open");
      openModal(document.getElementById(modalId));
    });
  });

  document.querySelectorAll("[data-report-modal]").forEach((modal) => {
    modal.querySelectorAll("[data-report-close]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        closeModal(modal);
      });
    });

    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        closeModal(modal);
      }
    });

    const card = modal.querySelector(".report-modal-card");
    if (card) {
      card.addEventListener("click", (event) => {
        event.stopPropagation();
      });
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const activeModal = document.querySelector(".report-modal.is-open");
    if (activeModal) {
      closeModal(activeModal);
    }
  });
});
