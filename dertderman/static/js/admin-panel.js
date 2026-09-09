(() => {
  const menu = document.querySelector('.ad-menu-button');
  const sidebar = document.querySelector('.ad-sidebar');
  const backdrop = document.querySelector('.ad-backdrop');
  const mobile = window.matchMedia('(max-width: 767px)');
  const closeMenu = () => {
    document.body.classList.remove('ad-menu-open');
    menu.setAttribute('aria-expanded', 'false');
    sidebar.inert = mobile.matches;
    backdrop.hidden = true;
  };
  document.body.classList.add('ad-enhanced');
  menu.hidden = false;
  closeMenu();
  menu.addEventListener('click', () => {
    if (document.body.classList.contains('ad-menu-open')) { closeMenu(); return; }
    document.body.classList.add('ad-menu-open');
    menu.setAttribute('aria-expanded', 'true');
    sidebar.inert = false;
    backdrop.hidden = false;
    sidebar.querySelector('a').focus();
  });
  backdrop.addEventListener('click', () => { closeMenu(); menu.focus(); });
  mobile.addEventListener('change', closeMenu);
  document.addEventListener('keydown', event => {
    if (!document.body.classList.contains('ad-menu-open')) return;
    if (event.key === 'Escape') { closeMenu(); menu.focus(); }
    if (event.key === 'Tab') {
      const links = [...sidebar.querySelectorAll('a, button')];
      const first = links[0], last = links[links.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  document.querySelectorAll('.feedback-close').forEach(button => {
    button.hidden = false;
    button.addEventListener('click', () => button.closest('.feedback').remove());
  });
  const dialog = document.querySelector('#admin-confirm');
  let pending = null;
  document.addEventListener('submit', event => {
    const button = event.submitter;
    if (!button?.matches('[data-confirm]') || button.dataset.confirmed === 'true') return;
    event.preventDefault();
    pending = { form: event.target, button };
    dialog.querySelector('#confirm-title').textContent = button.dataset.confirmTitle || 'İşlemi onaylıyor musunuz?';
    dialog.querySelector('#confirm-description').textContent = button.dataset.confirm;
    dialog.querySelector('[value="confirm"]').textContent = button.dataset.confirmAction || 'Reddet ve tamamla';
    dialog.showModal();
  });
  dialog.addEventListener('close', () => {
    if (dialog.returnValue === 'confirm' && pending) {
      pending.button.dataset.confirmed = 'true';
      pending.form.requestSubmit(pending.button);
      delete pending.button.dataset.confirmed;
    }
    pending?.button.focus();
    pending = null;
    dialog.returnValue = '';
  });
})();
