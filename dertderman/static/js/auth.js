/* Auth-only enhancement. Credentials stay in the normal Django POST form. */
(() => {
  document.querySelectorAll('[data-password-toggle]').forEach(button => {
    const input = document.getElementById(button.getAttribute('aria-controls'));
    if (!input || input.type !== 'password') return;
    button.hidden = false;
    button.parentElement.classList.add('password-enhanced');
    button.addEventListener('click', () => {
      const visible = input.type === 'password';
      input.type = visible ? 'text' : 'password';
      button.textContent = visible ? 'Gizle' : 'Göster';
      button.setAttribute('aria-pressed', String(visible));
      button.setAttribute('aria-label', `${input.labels[0].textContent.trim()}: ${button.textContent}`);
    });
  });
  document.querySelectorAll('.feedback-close').forEach(button => {
    button.hidden = false;
    button.addEventListener('click', () => button.closest('.feedback').remove());
  });
  document.querySelectorAll('[data-auth-form]').forEach(form => {
    const button = form.querySelector('[data-submit-label]');
    const label = button.querySelector('span');
    const original = label.textContent;
    const reset = () => {
      button.disabled = false;
      label.textContent = original;
      form.removeAttribute('aria-busy');
      form.dataset.submitting = 'false';
    };
    form.addEventListener('submit', event => {
      if (form.dataset.submitting === 'true') { event.preventDefault(); return; }
      form.dataset.submitting = 'true';
      form.setAttribute('aria-busy', 'true');
      button.disabled = true;
      label.textContent = button.dataset.submitLabel;
    });
    window.addEventListener('pageshow', reset);
  });
  // The server renders all errors and field descriptions, including without JS.
  document.querySelector('[data-auth-errors]')?.focus();
})();
