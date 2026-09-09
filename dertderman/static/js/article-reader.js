/* Progressive enhancement: links remain ordinary, crawlable article URLs. */
(() => {
  const dialog = document.querySelector('#article-reader');
  if (!dialog || typeof dialog.showModal !== 'function' || !window.fetch) return;

  const mount = dialog.querySelector('[data-reader-mount]');
  const scroller = dialog.querySelector('[data-reader-scroll]');
  const closeButton = dialog.querySelector('[data-reader-close]');
  const listURL = window.location.href;
  const pageTitle = document.title;
  let trigger = null;
  let controller = null;
  let scrollY = 0;
  let previousTop = '';
  let backdropStart = false;
  let sequence = 0;

  const message = (heading, description, url = null) => {
    const box = document.createElement('section');
    box.className = url ? 'reader-error' : 'reader-loading';
    const title = document.createElement('h2');
    title.id = 'reader-title';
    title.textContent = heading;
    const status = document.createElement('p');
    status.setAttribute('role', 'status');
    status.textContent = description;
    box.append(title, status);
    if (url) {
      const link = document.createElement('a');
      link.href = url;
      link.textContent = 'Yazıyı ayrı sayfada aç →';
      box.append(link);
    }
    mount.replaceChildren(box);
  };

  async function openReader(url, pushHistory = true) {
    controller?.abort();
    controller = new AbortController();
    const current = ++sequence;
    message('Yazı yükleniyor', 'Okuma alanı hazırlanıyor.');
    mount.setAttribute('aria-busy', 'true');
    // Save the list's scroll position in history before fixing the body.
    if (pushHistory) {
      window.history.pushState({ ddReader: { url, listURL } }, '', url);
    }
    if (!dialog.open) {
      scrollY = window.scrollY;
      previousTop = document.body.style.top;
      document.body.style.top = `-${scrollY}px`;
      document.body.classList.add('reader-open');
      dialog.showModal();
    }
    scroller.scrollTop = 0;
    closeButton.focus({ preventScroll: true });
    try {
      const response = await fetch(url, {
        headers: { 'X-Article-Reader': '1' },
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      });
      if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) throw new Error('Article unavailable');
      const html = await response.text();
      if (current !== sequence || !dialog.open) return;
      // This fragment is rendered by Django with normal autoescaping, just as
      // the direct page. Never interpret article content as user-supplied HTML.
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      const article = parsed.querySelector('[data-reader-article]');
      if (!article || !article.querySelector('#reader-title')) throw new Error('Missing article');
      mount.replaceChildren(document.importNode(article, true));
      document.title = `${mount.querySelector('#reader-title').textContent} | DertDerman Blog`;
    } catch (error) {
      if (error.name === 'AbortError' || current !== sequence || !dialog.open) return;
      message('Yazı şu anda açılamıyor', 'Bağlantınızı kontrol edin. Yazı yayından kaldırılmış da olabilir.', url);
    } finally {
      if (current === sequence) mount.removeAttribute('aria-busy');
    }
  }

  function requestClose() {
    if (!dialog.open) return;
    dialog.close();
    if (window.history.state?.ddReader?.listURL === listURL) window.history.back();
  }

  document.addEventListener('click', event => {
    const link = event.target.closest('a[data-article-link]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target === '_blank') return;
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    event.preventDefault();
    trigger = link;
    openReader(url.href);
  });
  closeButton.addEventListener('click', requestClose);
  dialog.addEventListener('cancel', event => { event.preventDefault(); requestClose(); });
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const focusable = [...dialog.querySelectorAll('a[href], button:not([disabled]), [tabindex="0"]')]
      .filter(element => element.getClientRects().length);
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  const outside = event => {
    const box = dialog.getBoundingClientRect();
    return event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom;
  };
  dialog.addEventListener('pointerdown', event => { backdropStart = event.target === dialog && outside(event); });
  dialog.addEventListener('click', event => {
    if (backdropStart && event.target === dialog && outside(event)) requestClose();
    backdropStart = false;
    if (event.target.closest('[data-reader-return]')) { event.preventDefault(); requestClose(); }
  });
  dialog.addEventListener('close', () => {
    ++sequence;
    controller?.abort();
    mount.replaceChildren();
    mount.removeAttribute('aria-busy');
    document.body.classList.remove('reader-open');
    document.body.style.top = previousTop;
    window.scrollTo(0, scrollY);
    document.title = pageTitle;
    if (trigger?.isConnected) trigger.focus({ preventScroll: true });
  });
  window.addEventListener('popstate', event => {
    const state = event.state?.ddReader;
    if (state?.listURL === listURL) openReader(state.url, false);
    else if (dialog.open) dialog.close();
  });
})();
