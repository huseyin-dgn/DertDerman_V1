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
  document.querySelectorAll('.ax-legal-dialog').forEach(dialog => {
    const scrollContainer = dialog.querySelector('.ax-legal-dialog-body');
    const acceptButton = dialog.querySelector('[data-legal-dialog-accept]');
    const updateScrollLock = () => {
      if (!scrollContainer || !acceptButton) return;
      const contentFits = scrollContainer.scrollHeight <= scrollContainer.clientHeight + 4;
      const reachedEnd = (
        scrollContainer.scrollTop + scrollContainer.clientHeight
        >= scrollContainer.scrollHeight - 4
      );
      acceptButton.disabled = !(contentFits || reachedEnd);
    };
    scrollContainer?.addEventListener('scroll', updateScrollLock, { passive: true });
    dialog.updateScrollLock = updateScrollLock;
    dialog.querySelector('[data-legal-dialog-close]')?.addEventListener('click', () => {
      dialog.close();
    });
    dialog.querySelector('[data-legal-dialog-accept]')?.addEventListener('click', event => {
      if (event.currentTarget.disabled) return;
      const checkbox = document.getElementById(event.currentTarget.dataset.checkboxId);
      if (!checkbox) return;
      checkbox.checked = true;
      checkbox.dispatchEvent(new Event('input', { bubbles: true }));
      checkbox.dispatchEvent(new Event('change', { bubbles: true }));
      dialog.dataset.accepted = 'true';
      dialog.close();
    });
    dialog.addEventListener('click', event => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener('close', () => {
      const acceptButton = dialog.querySelector('[data-legal-dialog-accept]');
      const checkbox = acceptButton
        ? document.getElementById(acceptButton.dataset.checkboxId)
        : null;
      if (checkbox && dialog.dataset.accepted !== 'true') {
        checkbox.checked = dialog.dataset.initialChecked === 'true';
      }
      dialog.returnFocus?.focus();
      delete dialog.returnFocus;
    });
  });
  const openLegalDialog = (trigger, dialogId = trigger.dataset.legalDialogTarget) => {
    const dialog = document.getElementById(dialogId);
    if (!dialog?.showModal) return false;
    const acceptButton = dialog.querySelector('[data-legal-dialog-accept]');
    const checkbox = acceptButton
      ? document.getElementById(acceptButton.dataset.checkboxId)
      : null;
    const scrollContainer = dialog.querySelector('.ax-legal-dialog-body');
    dialog.dataset.accepted = 'false';
    dialog.dataset.initialChecked = String(Boolean(checkbox?.checked));
    dialog.returnFocus = trigger;
    if (scrollContainer) scrollContainer.scrollTop = 0;
    if (acceptButton) acceptButton.disabled = true;
    dialog.showModal();
    requestAnimationFrame(() => {
      if (scrollContainer) scrollContainer.scrollTop = 0;
      dialog.updateScrollLock?.();
      dialog.querySelector('[data-legal-dialog-close]')?.focus();
    });
    return true;
  };
  document.querySelectorAll('[data-legal-dialog-target]').forEach(trigger => {
    trigger.addEventListener('click', event => {
      if (!openLegalDialog(trigger)) return;
      event.preventDefault();
      event.stopPropagation();
    });
  });
  document.querySelectorAll('.ax-consent').forEach(consent => {
    const checkbox = consent.querySelector('.ax-consent-checkbox');
    const label = consent.querySelector('label');
    const trigger = label?.querySelector('[data-legal-dialog-target]');
    if (!checkbox || !label || !trigger) return;
    checkbox.addEventListener('click', event => {
      event.stopPropagation();
      if (!checkbox.checked) return;
      event.preventDefault();
      checkbox.checked = false;
      openLegalDialog(checkbox, trigger.dataset.legalDialogTarget);
    });
    label.addEventListener('click', event => {
      if (event.target.closest('button, input')) return;
      event.preventDefault();
      openLegalDialog(trigger);
    });
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
