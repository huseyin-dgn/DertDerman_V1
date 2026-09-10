(() => {
  const menu = document.querySelector('.ad-menu-button');
  const sidebar = document.querySelector('.ad-sidebar');
  const backdrop = document.querySelector('.ad-backdrop');

  if (!menu || !sidebar || !backdrop) return;

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
    if (document.body.classList.contains('ad-menu-open')) {
      closeMenu();
      return;
    }

    document.body.classList.add('ad-menu-open');

    menu.setAttribute('aria-expanded', 'true');

    sidebar.inert = false;

    backdrop.hidden = false;

    const firstLink = sidebar.querySelector('a');

    if (firstLink) {
      firstLink.focus();
    }
  });

  backdrop.addEventListener('click', () => {
    closeMenu();
    menu.focus();
  });

  mobile.addEventListener('change', () => {
    closeMenu();
  });

  document.addEventListener('keydown', (event) => {
    if (!document.body.classList.contains('ad-menu-open')) return;

    if (event.key === 'Escape') {
      closeMenu();
      menu.focus();
      return;
    }

    if (event.key !== 'Tab') return;

    const links = [
      ...sidebar.querySelectorAll(
        'a[href], button:not([disabled])'
      ),
    ].filter((element) => !element.inert);

    if (!links.length) return;

    const first = links[0];
    const last = links[links.length - 1];

    if (
      event.shiftKey &&
      document.activeElement === first
    ) {
      event.preventDefault();
      last.focus();
    } else if (
      !event.shiftKey &&
      document.activeElement === last
    ) {
      event.preventDefault();
      first.focus();
    }
  });

  document
    .querySelectorAll('.feedback-close')
    .forEach((button) => {
      button.hidden = false;

      button.addEventListener('click', () => {
        button.closest('.feedback')?.remove();
      });
    });

  const dialog = document.querySelector('#admin-confirm');

  let pending = null;

  const resetAdminInteractionState = () => {
    closeMenu();

    document.body.classList.remove('ad-menu-open');
    document.body.style.overflow = '';

    backdrop.hidden = true;

    /*
     * Native <dialog> açık kalırsa tüm sayfa
     * top-layer nedeniyle tıklanamaz görünebilir.
     */
    if (dialog?.open) {
      dialog.close();
    }

    pending = null;

    if (dialog) {
      dialog.returnValue = '';
    }
  };

  if (dialog) {
    document.addEventListener('submit', (event) => {
      const button = event.submitter;

      if (
        !button?.matches('[data-confirm]') ||
        button.dataset.confirmed === 'true'
      ) {
        return;
      }

      event.preventDefault();

      pending = {
        form: event.target,
        button,
      };

      const title =
        dialog.querySelector('#confirm-title');

      const description =
        dialog.querySelector('#confirm-description');

      const confirmButton =
        dialog.querySelector('[value="confirm"]');

      if (title) {
        title.textContent =
          button.dataset.confirmTitle ||
          'İşlemi onaylıyor musunuz?';
      }

      if (description) {
        description.textContent =
          button.dataset.confirm || '';
      }

      if (confirmButton) {
        confirmButton.textContent =
          button.dataset.confirmAction ||
          'Reddet ve tamamla';
      }

      if (!dialog.open) {
        dialog.showModal();
      }
    });

    dialog.addEventListener('close', () => {
      if (
        dialog.returnValue === 'confirm' &&
        pending
      ) {
        pending.button.dataset.confirmed = 'true';

        pending.form.requestSubmit(
          pending.button
        );

        delete pending.button.dataset.confirmed;
      }

      if (pending?.button?.isConnected) {
        pending.button.focus();
      }

      pending = null;

      dialog.returnValue = '';
    });

    dialog.addEventListener('cancel', () => {
      pending = null;
    });
  }

  window.addEventListener('pagehide', () => {
    resetAdminInteractionState();
  });

  window.addEventListener('pageshow', (event) => {
    if (!event.persisted) return;

    resetAdminInteractionState();
  });
})();