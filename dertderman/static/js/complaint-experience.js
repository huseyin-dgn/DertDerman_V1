(() => {
  "use strict";

  document.querySelectorAll("[data-character-count]").forEach((field) => {
    const maximum = Number(field.getAttribute("maxlength"));
    if (!maximum) return;
    const counter = document.createElement("span");
    counter.className = "character-counter";
    counter.setAttribute("aria-live", "polite");
    field.insertAdjacentElement("afterend", counter);
    const update = () => { counter.textContent = `${field.value.length} / ${maximum}`; };
    field.addEventListener("input", update);
    update();
  });

  document.querySelectorAll("[data-submit-form]").forEach((form) => {
    form.addEventListener("submit", () => {
      if (!form.checkValidity()) return;
      const button = form.querySelector("button[type='submit']");
      if (!button) return;
      button.disabled = true;
      button.textContent = "Gönderiliyor…";
    });
  });
})();

document.querySelectorAll('[data-emoji-picker]').forEach((picker) => {
  const input = picker.querySelector('input[name="reaction_type"]');
  const status = picker.querySelector('.emoji-picker-status');
  let submitting = false;
  const submitReaction = (emoji) => {
    if (submitting || !emoji) return;
    submitting = true;
    input.value = emoji;
    if (status) status.textContent = 'Tepki güncelleniyor…';
    picker.setAttribute('aria-busy', 'true');
    picker.querySelectorAll('button').forEach((button) => { button.disabled = true; });
    picker.requestSubmit();
  };
  picker.querySelectorAll('[data-emoji]').forEach((button) => button.addEventListener('click', () => {
    submitReaction(button.dataset.emoji);
  }));
  input.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    submitReaction(input.value.trim());
  });
  input.addEventListener('change', () => submitReaction(input.value.trim()));
});

document.querySelectorAll('[data-withdraw-open]').forEach((button) => button.addEventListener('click', () => {
  const dialog = document.querySelector('[data-withdraw-dialog]');
  if (dialog) dialog.showModal();
}));
document.querySelectorAll('[data-withdraw-close]').forEach((button) => button.addEventListener('click', () => button.closest('dialog').close()));
